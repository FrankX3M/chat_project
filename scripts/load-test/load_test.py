#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
load_test.py — эмулятор нагрузки пользователей на заданный IP/хост + анализ метрик в реальном времени.

Что делает:
  * Поднимает N "виртуальных пользователей" (asyncio-корутины), которые ходят по HTTP
    и/или держат WebSocket-соединения к тестируемому серверу — как обычные пользователи чата.
  * Постепенно увеличивает нагрузку (ramp-up), держит её заданное время (duration).
  * Собирает метрики по каждому запросу/сообщению: латентность, успех/ошибка, тип, время.
  * В реальном времени анализирует скользящее окно метрик (RPS, error rate, перцентили
    латентности) и сравнивает с порогами — если "что-то пошло не так", печатает ALERT.
  * По завершении сохраняет сырые данные (CSV), сводный отчёт (JSON), человекочитаемую
    сводку в консоль и (если установлен matplotlib) график latency/error rate по времени.

ВАЖНО: используйте только против систем, которыми вы владеете или на тестирование
которых у вас есть явное разрешение. Скрипт умеет создавать серьёзную нагрузку.

Примеры запуска:
  # Простой HTTP GET-нагрузочный тест: 200 пользователей, разгон 20 сек, длительность 120 сек
  python3 load_test.py --protocol http --host 10.0.0.5 --port 8080 \
      --http-path /api/health --users 200 --ramp-up 20 --duration 120

  # Сценарий логина + отправки сообщений в чат (JSON-сценарий)
  python3 load_test.py --protocol http --host 10.0.0.5 --port 8080 \
      --scenario scenario.example.json --users 500 --ramp-up 30 --duration 300

  # WebSocket-чат: подключение + периодическая отправка сообщений
  python3 load_test.py --protocol ws --host 10.0.0.5 --port 8080 \
      --ws-path /ws/chat --users 300 --ramp-up 30 --duration 180 \
      --ws-message "привет от {id}, сообщение #{seq}"

  # Одновременно HTTP и WS (половина пользователей на каждый протокол)
  python3 load_test.py --protocol both --host 10.0.0.5 --port 8080 \
      --http-path /api/rooms --ws-path /ws/chat --users 400 --ramp-up 40 --duration 300
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import random
import signal
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

try:
    import aiohttp
except ImportError:
    aiohttp = None

try:
    import websockets
except ImportError:
    websockets = None


# --------------------------------------------------------------------------- #
# Метрики
# --------------------------------------------------------------------------- #

@dataclass
class RequestRecord:
    ts: float           # unix timestamp завершения запроса
    kind: str            # "http" | "ws"
    name: str             # имя шага/действия
    ok: bool
    latency_ms: float
    error: str = ""
    status: int = 0


@dataclass
class Alert:
    ts: float
    message: str


class MetricsStore:
    """Потокобезопасное (в рамках одного event loop) хранилище результатов запросов."""

    def __init__(self) -> None:
        self.records: list[RequestRecord] = []
        self.alerts: list[Alert] = []
        self._lock = asyncio.Lock()
        self.start_ts = time.time()

    async def add(self, rec: RequestRecord) -> None:
        async with self._lock:
            self.records.append(rec)

    def window(self, seconds: float, now: Optional[float] = None) -> list[RequestRecord]:
        now = now if now is not None else time.time()
        cutoff = now - seconds
        # records добавляются почти по порядку времени, поэтому идём с конца
        out = []
        for r in reversed(self.records):
            if r.ts < cutoff:
                break
            out.append(r)
        return out

    def add_alert(self, message: str) -> None:
        a = Alert(ts=time.time(), message=message)
        self.alerts.append(a)
        elapsed = a.ts - self.start_ts
        print(f"[{elapsed:7.1f}s] ⚠️  ALERT: {message}", flush=True)


def percentiles(values: list[float], ps: tuple[int, ...] = (50, 90, 95, 99)) -> dict[int, float]:
    if not values:
        return {p: 0.0 for p in ps}
    s = sorted(values)
    out = {}
    for p in ps:
        if len(s) == 1:
            out[p] = s[0]
            continue
        k = (len(s) - 1) * (p / 100)
        f = int(k)
        c = min(f + 1, len(s) - 1)
        if f == c:
            out[p] = s[f]
        else:
            out[p] = s[f] + (s[c] - s[f]) * (k - f)
    return out


# --------------------------------------------------------------------------- #
# Шаблонизация (подстановка {id}, {seq}, {ts} в путях/телах запросов)
# --------------------------------------------------------------------------- #

def render(template: Any, ctx: dict) -> Any:
    if isinstance(template, str):
        try:
            return template.format(**ctx)
        except (KeyError, IndexError):
            return template
    if isinstance(template, dict):
        return {k: render(v, ctx) for k, v in template.items()}
    if isinstance(template, list):
        return [render(v, ctx) for v in template]
    return template


def get_by_path(obj: Any, path: str) -> Any:
    """Достаёт значение из вложенного dict по пути вида 'data.token'."""
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


# --------------------------------------------------------------------------- #
# HTTP-нагрузка
# --------------------------------------------------------------------------- #

DEFAULT_HTTP_STEP = {"name": "request", "method": "GET", "path": "/", "weight": 1}


def load_scenario(path: Optional[str]) -> dict:
    if not path:
        return {"steps": [DEFAULT_HTTP_STEP]}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


async def http_virtual_user(
    user_id: int,
    base_url: str,
    scenario: dict,
    duration_end: float,
    think_time: tuple[float, float],
    metrics: MetricsStore,
    session: "aiohttp.ClientSession",
    auth_header: str,
    timeout_s: float,
    stop_event: asyncio.Event,
) -> None:
    ctx = {"id": user_id, "seq": 0, "ts": int(time.time())}
    token: Optional[str] = None

    once_steps = [s for s in scenario["steps"] if s.get("once")]
    repeat_steps = [s for s in scenario["steps"] if not s.get("once")]
    if not repeat_steps:
        repeat_steps = once_steps or [DEFAULT_HTTP_STEP]

    async def do_step(step: dict) -> bool:
        nonlocal token
        ctx["seq"] += 1
        method = step.get("method", "GET").upper()
        path = render(step.get("path", "/"), ctx)
        url = base_url.rstrip("/") + path
        headers = dict(step.get("headers", {}))
        if step.get("auth") and token:
            headers[auth_header.split(":")[0].strip() if ":" in auth_header else "Authorization"] = \
                (auth_header.format(token=token) if "{token}" in auth_header else f"Bearer {token}")
        json_body = render(step.get("json"), ctx) if step.get("json") is not None else None

        t0 = time.perf_counter()
        ok, status, err = True, 0, ""
        try:
            async with session.request(
                method, url, json=json_body, headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout_s),
            ) as resp:
                status = resp.status
                ok = status < 400
                body = None
                if step.get("save_token"):
                    try:
                        body = await resp.json(content_type=None)
                    except Exception:
                        body = None
                else:
                    await resp.read()
                if step.get("save_token") and body is not None:
                    val = get_by_path(body, step.get("token_path", "token"))
                    if val:
                        token = val
                if not ok:
                    err = f"http_{status}"
        except asyncio.TimeoutError:
            ok, err = False, "timeout"
        except Exception as e:  # noqa: BLE001
            ok, err = False, f"{type(e).__name__}: {e}"
        latency_ms = (time.perf_counter() - t0) * 1000
        await metrics.add(RequestRecord(
            ts=time.time(), kind="http", name=step.get("name", path),
            ok=ok, latency_ms=latency_ms, error=err, status=status,
        ))
        return ok

    for step in once_steps:
        if stop_event.is_set():
            return
        await do_step(step)

    weights = [max(s.get("weight", 1), 0.001) for s in repeat_steps]
    while time.time() < duration_end and not stop_event.is_set():
        step = random.choices(repeat_steps, weights=weights, k=1)[0]
        await do_step(step)
        await asyncio.sleep(random.uniform(*think_time))


# --------------------------------------------------------------------------- #
# WebSocket-нагрузка
# --------------------------------------------------------------------------- #

async def ws_authenticate(
    session: "aiohttp.ClientSession",
    base_url: str,
    ctx: dict,
    auth_url: str,
    auth_method: str,
    auth_body_template: Optional[str],
    token_path: str,
    timeout_s: float,
) -> str:
    """Дёргает HTTP-эндпоинт логина перед WS-подключением и возвращает токен.

    Нужен для приложений вроде этого чата, где WS требует ?token=... из
    отдельного REST-логина (см. /api/v1/auth/anonymous + /ws/connect?token=).
    """
    url = base_url.rstrip("/") + auth_url.format(**ctx)
    body = None
    if auth_body_template:
        body = json.loads(auth_body_template.format(**ctx))
    async with session.request(
        auth_method.upper(), url, json=body,
        timeout=aiohttp.ClientTimeout(total=timeout_s),
    ) as resp:
        resp.raise_for_status()
        data = await resp.json(content_type=None)
    token = get_by_path(data, token_path)
    if not token:
        raise RuntimeError(f"в ответе {auth_url} не найдено поле '{token_path}'")
    return token


async def ws_virtual_user(
    user_id: int,
    ws_url: str,
    duration_end: float,
    think_time: tuple[float, float],
    message_template: str,
    wait_reply: bool,
    reply_timeout_s: float,
    metrics: MetricsStore,
    stop_event: asyncio.Event,
    auth_session: Optional["aiohttp.ClientSession"] = None,
    base_url: str = "",
    auth_url: Optional[str] = None,
    auth_method: str = "POST",
    auth_body_template: Optional[str] = None,
    auth_token_path: str = "access_token",
) -> None:
    ctx = {"id": user_id, "seq": 0, "ts": int(time.time()), "token": ""}

    if auth_url:
        t0 = time.perf_counter()
        try:
            ctx["token"] = await ws_authenticate(
                auth_session, base_url, ctx, auth_url, auth_method,
                auth_body_template, auth_token_path, reply_timeout_s,
            )
            await metrics.add(RequestRecord(
                ts=time.time(), kind="ws", name="ws_auth", ok=True,
                latency_ms=(time.perf_counter() - t0) * 1000,
            ))
        except Exception as e:  # noqa: BLE001
            await metrics.add(RequestRecord(
                ts=time.time(), kind="ws", name="ws_auth", ok=False,
                latency_ms=(time.perf_counter() - t0) * 1000, error=f"{type(e).__name__}: {e}",
            ))
            return

    url = ws_url.format(**ctx)

    t0 = time.perf_counter()
    try:
        conn = await asyncio.wait_for(websockets.connect(url, open_timeout=reply_timeout_s), timeout=reply_timeout_s)
    except Exception as e:  # noqa: BLE001
        await metrics.add(RequestRecord(
            ts=time.time(), kind="ws", name="connect", ok=False,
            latency_ms=(time.perf_counter() - t0) * 1000, error=f"{type(e).__name__}: {e}",
        ))
        return

    await metrics.add(RequestRecord(
        ts=time.time(), kind="ws", name="connect", ok=True,
        latency_ms=(time.perf_counter() - t0) * 1000,
    ))

    try:
        while time.time() < duration_end and not stop_event.is_set():
            ctx["seq"] += 1
            msg = message_template.format(**ctx)
            t0 = time.perf_counter()
            ok, err = True, ""
            try:
                await conn.send(msg)
                if wait_reply:
                    await asyncio.wait_for(conn.recv(), timeout=reply_timeout_s)
            except asyncio.TimeoutError:
                ok, err = False, "reply_timeout"
            except Exception as e:  # noqa: BLE001
                ok, err = False, f"{type(e).__name__}: {e}"
            latency_ms = (time.perf_counter() - t0) * 1000
            await metrics.add(RequestRecord(
                ts=time.time(), kind="ws", name="message", ok=ok,
                latency_ms=latency_ms, error=err,
            ))
            if not ok and "Connection" in err:
                break
            await asyncio.sleep(random.uniform(*think_time))
    finally:
        try:
            await conn.close()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Планировщик пользователей (ramp-up)
# --------------------------------------------------------------------------- #

async def spawn_users(
    total: int,
    ramp_up_s: float,
    user_factory,
) -> list[asyncio.Task]:
    tasks: list[asyncio.Task] = []
    if total <= 0:
        return tasks
    delay = ramp_up_s / total if ramp_up_s > 0 else 0
    for i in range(total):
        tasks.append(asyncio.create_task(user_factory(i)))
        if delay:
            await asyncio.sleep(delay)
    return tasks


# --------------------------------------------------------------------------- #
# Анализатор в реальном времени
# --------------------------------------------------------------------------- #

async def analyzer_loop(
    metrics: MetricsStore,
    window_s: float,
    interval_s: float,
    err_rate_threshold: float,
    p95_threshold_ms: float,
    min_rps_expected: float,
    stop_event: asyncio.Event,
    run_end: float,
) -> None:
    consecutive_bad = 0
    while not stop_event.is_set() and time.time() < run_end + interval_s:
        await asyncio.sleep(interval_s)
        now = time.time()
        recs = metrics.window(window_s, now=now)
        elapsed = now - metrics.start_ts
        if not recs:
            print(f"[{elapsed:7.1f}s] нет данных за последние {window_s:.0f}с "
                  f"(пользователи ещё разгоняются либо сервер не отвечает)", flush=True)
            continue
        total = len(recs)
        errors = [r for r in recs if not r.ok]
        err_rate = len(errors) / total * 100
        lat = percentiles([r.latency_ms for r in recs if r.ok] or [r.latency_ms for r in recs])
        rps = total / window_s

        status_bits = (
            f"rps={rps:6.1f}  errors={len(errors):4d}/{total:4d} ({err_rate:5.1f}%)  "
            f"p50={lat[50]:7.1f}ms  p95={lat[95]:7.1f}ms  p99={lat[99]:7.1f}ms"
        )
        print(f"[{elapsed:7.1f}s] {status_bits}", flush=True)

        bad = False
        if err_rate > err_rate_threshold:
            metrics.add_alert(
                f"error rate {err_rate:.1f}% > порога {err_rate_threshold:.1f}% "
                f"(за последние {window_s:.0f}с)"
            )
            bad = True
        if lat[95] > p95_threshold_ms:
            metrics.add_alert(
                f"p95 latency {lat[95]:.0f}ms > порога {p95_threshold_ms:.0f}ms "
                f"(за последние {window_s:.0f}с)"
            )
            bad = True
        if min_rps_expected > 0 and rps < min_rps_expected:
            metrics.add_alert(
                f"RPS просел до {rps:.1f} (ожидалось от {min_rps_expected:.1f}) — "
                f"похоже, сервер не успевает отвечать"
            )
            bad = True

        consecutive_bad = consecutive_bad + 1 if bad else 0
        if consecutive_bad >= 3:
            metrics.add_alert(
                "3 замера подряд вне нормы — вероятна деградация сервиса под нагрузкой"
            )


# --------------------------------------------------------------------------- #
# Итоговый отчёт
# --------------------------------------------------------------------------- #

def build_summary(metrics: MetricsStore) -> dict:
    recs = metrics.records
    total = len(recs)
    ok_recs = [r for r in recs if r.ok]
    err_recs = [r for r in recs if not r.ok]
    duration = (recs[-1].ts - metrics.start_ts) if recs else 0.0
    lat_all = percentiles([r.latency_ms for r in recs])
    lat_ok = percentiles([r.latency_ms for r in ok_recs])

    by_kind: dict[str, dict] = {}
    for kind in {r.kind for r in recs}:
        kr = [r for r in recs if r.kind == kind]
        by_kind[kind] = {
            "total": len(kr),
            "ok": sum(1 for r in kr if r.ok),
            "errors": sum(1 for r in kr if not r.ok),
        }

    err_breakdown: dict[str, int] = {}
    for r in err_recs:
        key = r.error or f"status_{r.status}"
        err_breakdown[key] = err_breakdown.get(key, 0) + 1

    return {
        "started_at": datetime.fromtimestamp(metrics.start_ts).isoformat(),
        "duration_s": round(duration, 1),
        "total_requests": total,
        "success": len(ok_recs),
        "errors": len(err_recs),
        "error_rate_pct": round(len(err_recs) / total * 100, 2) if total else 0.0,
        "avg_rps": round(total / duration, 2) if duration > 0 else 0.0,
        "latency_ms": {"all": lat_all, "success_only": lat_ok},
        "by_kind": by_kind,
        "error_breakdown": err_breakdown,
        "alerts": [{"ts": datetime.fromtimestamp(a.ts).isoformat(), "message": a.message} for a in metrics.alerts],
        "verdict": "DEGRADED" if metrics.alerts else "OK",
    }


def write_reports(metrics: MetricsStore, out_dir: Path, make_plot: bool) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = build_summary(metrics)

    with open(out_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    with open(out_dir / "raw_records.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ts", "kind", "name", "ok", "latency_ms", "status", "error"])
        for r in metrics.records:
            w.writerow([f"{r.ts:.3f}", r.kind, r.name, r.ok, f"{r.latency_ms:.2f}", r.status, r.error])

    if make_plot:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            recs = metrics.records
            if recs:
                t0 = metrics.start_ts
                xs = [r.ts - t0 for r in recs]
                lat = [r.latency_ms for r in recs]
                fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
                ax1.scatter(xs, lat, s=6, alpha=0.4, color="#3b6fd6")
                ax1.set_ylabel("latency, ms")
                ax1.set_title("Load test: latency over time")
                ax1.grid(alpha=0.3)

                bucket = 5
                buckets: dict[int, list[RequestRecord]] = {}
                for r, x in zip(recs, xs):
                    buckets.setdefault(int(x // bucket), []).append(r)
                bx, by = [], []
                for k in sorted(buckets):
                    grp = buckets[k]
                    err_rate = sum(1 for r in grp if not r.ok) / len(grp) * 100
                    bx.append(k * bucket)
                    by.append(err_rate)
                ax2.plot(bx, by, color="#d64545", linewidth=1.5)
                ax2.fill_between(bx, by, color="#d64545", alpha=0.15)
                ax2.set_ylabel("error rate, %")
                ax2.set_xlabel("seconds since start")
                ax2.grid(alpha=0.3)

                for a in metrics.alerts:
                    ax1.axvline(a.ts - t0, color="orange", linestyle="--", alpha=0.6)

                fig.tight_layout()
                fig.savefig(out_dir / "load_test_report.png", dpi=130)
                plt.close(fig)
        except ImportError:
            print("(matplotlib не установлен — график не сгенерирован; "
                  "pip install matplotlib --break-system-packages)")

    return summary


def print_final_summary(summary: dict) -> None:
    print("\n" + "=" * 70)
    print("ИТОГОВЫЙ ОТЧЁТ")
    print("=" * 70)
    print(f"Длительность:      {summary['duration_s']} с")
    print(f"Всего запросов:    {summary['total_requests']}")
    print(f"Успешно:           {summary['success']}")
    print(f"Ошибок:            {summary['errors']} ({summary['error_rate_pct']}%)")
    print(f"Средний RPS:       {summary['avg_rps']}")
    lat = summary["latency_ms"]["success_only"]
    print(f"Latency (success): p50={lat[50]:.0f}ms  p90={lat[90]:.0f}ms  "
          f"p95={lat[95]:.0f}ms  p99={lat[99]:.0f}ms")
    if summary["error_breakdown"]:
        print("Разбивка ошибок:")
        for k, v in sorted(summary["error_breakdown"].items(), key=lambda kv: -kv[1]):
            print(f"  - {k}: {v}")
    print(f"Алертов во время теста: {len(summary['alerts'])}")
    print(f"ВЕРДИКТ: {summary['verdict']}"
          + ("  — во время теста были обнаружены признаки деградации, см. alerts в summary.json"
             if summary["verdict"] == "DEGRADED" else "  — отклонений от пороговых значений не найдено"))
    print("=" * 70)


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Эмулятор нагрузки пользователей + анализ метрик в реальном времени.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--host", required=True, help="IP или хост тестируемого сервера")
    p.add_argument("--port", type=int, default=80, help="Порт (по умолчанию 80)")
    p.add_argument("--protocol", choices=["http", "ws", "both"], default="http")
    p.add_argument("--scheme", default=None, help="http/https для HTTP (по умолчанию http, или https если --tls)")
    p.add_argument("--tls", action="store_true", help="Использовать https:// и wss://")

    p.add_argument("--users", type=int, default=50, help="Общее число виртуальных пользователей")
    p.add_argument("--ramp-up", type=float, default=10, help="Время разгона до полной нагрузки, сек")
    p.add_argument("--duration", type=float, default=60, help="Длительность удержания нагрузки, сек (после разгона)")
    p.add_argument("--think-time", default="0.5-2.0", help="Пауза между действиями пользователя, сек, диапазон 'min-max'")
    p.add_argument("--timeout", type=float, default=10.0, help="Таймаут одного запроса/сообщения, сек")

    p.add_argument("--http-path", default="/", help="Путь для простого HTTP-теста (если не задан --scenario)")
    p.add_argument("--http-method", default="GET")
    p.add_argument("--scenario", default=None, help="JSON-файл сценария (см. scenario.example.json)")
    p.add_argument("--auth-header", default="Authorization", help="Имя заголовка авторизации или шаблон 'Authorization: Bearer {token}'")

    p.add_argument("--ws-path", default="/ws", help="Путь WebSocket (поддерживает {id}, и {token} если задан --ws-auth-url)")
    p.add_argument("--ws-message", default="ping from user {id} #{seq}", help="Шаблон сообщения для WS")
    p.add_argument("--ws-wait-reply", action="store_true", help="Ждать ответ сервера на каждое сообщение (для замера round-trip latency)")
    p.add_argument("--ws-auth-url", default=None,
                    help="HTTP-путь логина, который нужно дёрнуть перед WS-подключением, чтобы получить токен "
                         "(например /api/v1/auth/anonymous). Подставляет {id} в тело запроса.")
    p.add_argument("--ws-auth-method", default="POST")
    p.add_argument("--ws-auth-body", default='{{"device_id": "loadtest-{id}"}}',
                    help="JSON-шаблон тела запроса логина для WS (поддерживает {id})")
    p.add_argument("--ws-auth-token-path", default="access_token",
                    help="Путь к полю с токеном в ответе логина (например 'access_token' или 'data.token')")

    p.add_argument("--window", type=float, default=5.0, help="Размер скользящего окна анализа, сек")
    p.add_argument("--report-interval", type=float, default=5.0, help="Как часто печатать статус, сек")
    p.add_argument("--error-rate-threshold", type=float, default=5.0, help="Порог error rate, %%")
    p.add_argument("--p95-threshold-ms", type=float, default=1000.0, help="Порог p95 latency, мс")
    p.add_argument("--min-rps", type=float, default=0.0, help="Минимально ожидаемый RPS (0 = не проверять)")

    p.add_argument("--out-dir", default="loadtest_report", help="Куда сохранить отчёты")
    p.add_argument("--no-plot", action="store_true", help="Не строить график (даже если matplotlib установлен)")
    return p.parse_args()


async def run(args: argparse.Namespace) -> dict:
    if (args.protocol in ("http", "both") or args.ws_auth_url) and aiohttp is None:
        sys.exit("Нужен пакет aiohttp: pip install aiohttp --break-system-packages")
    if args.protocol in ("ws", "both") and websockets is None:
        sys.exit("Нужен пакет websockets: pip install websockets --break-system-packages")

    scheme_http = "https" if args.tls else (args.scheme or "http")
    scheme_ws = "wss" if args.tls else "ws"
    base_url = f"{scheme_http}://{args.host}:{args.port}"
    ws_url = f"{scheme_ws}://{args.host}:{args.port}{args.ws_path}"

    tmin, tmax = (float(x) for x in args.think_time.split("-"))
    think_time = (tmin, tmax)

    scenario = load_scenario(args.scenario)
    if not args.scenario:
        scenario = {"steps": [{"name": "request", "method": args.http_method, "path": args.http_path, "weight": 1}]}

    metrics = MetricsStore()
    stop_event = asyncio.Event()

    def handle_signal():
        print("\nПолучен сигнал остановки — завершаю виртуальных пользователей...", flush=True)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handle_signal)
        except NotImplementedError:
            pass  # Windows

    n_http = args.users if args.protocol == "http" else (args.users // 2 if args.protocol == "both" else 0)
    n_ws = args.users if args.protocol == "ws" else (args.users - n_http if args.protocol == "both" else 0)

    ramp_end = time.time() + args.ramp_up
    duration_end = ramp_end + args.duration
    run_end = duration_end

    tasks: list[asyncio.Task] = []

    print(f"Старт теста: host={args.host}:{args.port} протокол={args.protocol} "
          f"пользователей={args.users} (http={n_http}, ws={n_ws}) "
          f"ramp-up={args.ramp_up}с duration={args.duration}с", flush=True)

    analyzer_task = asyncio.create_task(analyzer_loop(
        metrics, args.window, args.report_interval,
        args.error_rate_threshold, args.p95_threshold_ms, args.min_rps,
        stop_event, run_end,
    ))

    needs_http_session = n_http > 0 or bool(args.ws_auth_url)

    def make_ws_user(i: int, session):
        return ws_virtual_user(
            i, ws_url, duration_end, think_time, args.ws_message,
            args.ws_wait_reply, args.timeout, metrics, stop_event,
            auth_session=session, base_url=base_url, auth_url=args.ws_auth_url,
            auth_method=args.ws_auth_method, auth_body_template=args.ws_auth_body,
            auth_token_path=args.ws_auth_token_path,
        )

    if needs_http_session:
        connector = aiohttp.TCPConnector(limit=0)
        async with aiohttp.ClientSession(connector=connector) as session:
            if n_http > 0:
                http_tasks = await spawn_users(
                    n_http, args.ramp_up,
                    lambda i: http_virtual_user(
                        i, base_url, scenario, duration_end, think_time, metrics,
                        session, args.auth_header, args.timeout, stop_event,
                    ),
                )
                tasks.extend(http_tasks)

            if n_ws > 0:
                ws_ramp = max(args.ramp_up - args.ramp_up * (n_http / max(args.users, 1)), 0) if n_http > 0 else args.ramp_up
                ws_tasks = await spawn_users(n_ws, ws_ramp, lambda i: make_ws_user(i, session))
                tasks.extend(ws_tasks)

            await asyncio.gather(*tasks, return_exceptions=True)
    elif n_ws > 0:
        ws_tasks = await spawn_users(n_ws, args.ramp_up, lambda i: make_ws_user(i, None))
        tasks.extend(ws_tasks)
        await asyncio.gather(*tasks, return_exceptions=True)

    stop_event.set()
    analyzer_task.cancel()
    try:
        await analyzer_task
    except asyncio.CancelledError:
        pass

    summary = write_reports(metrics, Path(args.out_dir), make_plot=not args.no_plot)
    print_final_summary(summary)
    print(f"\nОтчёты сохранены в: {Path(args.out_dir).resolve()}")
    return summary


def main() -> None:
    args = parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
