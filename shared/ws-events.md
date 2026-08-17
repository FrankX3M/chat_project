# WebSocket-контракт

Единый источник правды — `server/app/schemas/ws_events.py`. Этот файл — человекочитаемое
зеркало для клиентов (web/mobile). При любом изменении схемы обновлять оба места
одновременно (см. CLAUDE.md, принцип 2).

**Endpoint:** `WS /ws/connect?token={access_token}`

Один сокет на пользователя обслуживает и ожидание матча, и сам чат.

## Клиент → сервер

| event | payload | Когда отправляется |
|---|---|---|
| `join_queue` | `{ topic?, partner_gender?, partner_age_min?, partner_age_max? }` | Альтернатива `POST /search/start` — постановка в очередь прямо по сокету |
| `cancel_queue` | `{}` | Отмена поиска |
| `message` | `{ room_id, content, content_type }` | Отправка сообщения в чате |
| `typing` | `{ room_id, is_typing }` | Индикатор набора текста (throttle на клиенте, не чаще раза в 1-2 сек) |
| `leave` | `{ room_id }` | "Стоп" / "Далее" |

## Сервер → клиент

| event | payload | Когда отправляется |
|---|---|---|
| `matched` | `{ room_id, partner: { gender, age_range, topic } }` | Найдена пара |
| `message` | `{ room_id, sender: "partner", content, created_at }` | Сообщение от собеседника |
| `typing` | `{ room_id, is_typing }` | Собеседник печатает |
| `partner_left` | `{ room_id, reason }` | Собеседник вышел / отменил / таймаут реконнекта |
| `queue_position` | `{ position, estimated_wait? }` | Обновление позиции в очереди (после `join_queue`) |
| `error` | `{ code, message }` | Невалидный payload, комната не найдена, доступ запрещён и т.п. |

## Реконнект (см. CLAUDE.md / project-structure.md 6.7)

При разрыве соединения сервер ждёт `ROOM_RECONNECT_GRACE_SECONDS` (по умолчанию 20с) —
если клиент переподключился и снова открыл сокет с тем же токеном, комната продолжает
жить молча. Если нет — комната закрывается с `end_reason=timeout`, партнёр получает
`partner_left { reason: "timeout" }`.
