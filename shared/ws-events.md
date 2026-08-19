# WebSocket-контракт

Единый источник правды — `server/app/schemas/ws_events.py`. Этот файл — человекочитаемое
зеркало для клиентов (web/mobile). При любом изменении схемы обновлять оба места
одновременно (см. CLAUDE.md, принцип 2).

**Endpoint:** `WS /ws/connect?token={access_token}`

Один сокет на пользователя обслуживает и ожидание матча, и сам чат.

## Клиент → сервер

| event | payload | Когда отправляется |
|---|---|---|
| `join_queue` | `{ topic?, partner_gender?, partner_age_min?, partner_age_max?, partner_age_ranges?, plot_role? }` | Альтернатива `POST /search/start` — постановка в очередь прямо по сокету |
| `cancel_queue` | `{}` | Отмена поиска |
| `message` | `{ room_id, content, content_type, captcha_token? }` | Отправка сообщения в чате |
| `typing` | `{ room_id, is_typing }` | Индикатор набора текста (throttle на клиенте, не чаще раза в 1-2 сек) |
| `leave` | `{ room_id }` | "Стоп" / "Далее" |

`partner_age_ranges` (`[{ min, max }, ...]`) — task190826_v2: во вкладках "Общение" и
"Флирт 18+" возраст собеседника — множественный выбор (минимум один диапазон на клиенте).
Матчинг считает партнёра подходящим, если его возраст попадает в ЛЮБОЙ из присланных
диапазонов (см. `matchmaking/filters.py::_age_ok`). Легаси-поля `partner_age_min`/
`partner_age_max` остаются как одиночный диапазон для обратной совместимости и как
запасной вариант, если `partner_age_ranges` не передан; когда оба присутствуют,
приоритет — у `partner_age_ranges`. Для темы "Ролка" (`roleplay`) сервер игнорирует все
три поля — тема без фильтра по возрасту.

`plot_role` (`seeking_plot` \| `offering_plot`) — task190826: обязателен только для темы
"Ролка" (`roleplay`), проверяется на сервере (`matchmaking/topics.py::validate_topic_selection`).
Для тем "Флирт 18+" (`flirt18`) и "Ролка" сервер также требует, чтобы `partner_gender` был
строго противоположен собственному полу пользователя — иначе `error{code: invalid_topic_filters}`.

`captcha_token` — task190826: простая антиспам-капча (Google reCAPTCHA) для первых
`RECAPTCHA_MESSAGE_THRESHOLD` (по умолчанию 5) сообщений пользователя, только пока
`RECAPTCHA_ENABLED=true` на сервере. Пока порог не пройден и токен отсутствует/невалиден —
сервер отвечает `error{code: captcha_required}` вместо доставки сообщения.

## Сервер → клиент

| event | payload | Когда отправляется |
|---|---|---|
| `matched` | `{ room_id, partner: { gender, age_range, topic } }` | Найдена пара |
| `message` | `{ room_id, sender: "partner", content, created_at }` | Сообщение от собеседника |
| `typing` | `{ room_id, is_typing }` | Собеседник печатает |
| `partner_left` | `{ room_id, reason }` | Собеседник вышел / отменил / таймаут реконнекта |
| `queue_position` | `{ position, estimated_wait? }` | Обновление позиции в очереди (после `join_queue`) |
| `error` | `{ code, message }` | Невалидный payload, комната не найдена, доступ запрещён и т.п. |

Известные значения `code`: `unsupported_event`, `age_verification_required`, `invalid_topic_filters`
(task190826 — пол/роль сюжета не подходят теме), `room_not_found`, `rate_limited`,
`captcha_required` (task190826), `message_rejected` (сработал `content_filter` — см.
`moderation/content_filter.py`).

## Реконнект (см. CLAUDE.md / project-structure.md 6.7)

При разрыве соединения сервер ждёт `ROOM_RECONNECT_GRACE_SECONDS` (по умолчанию 20с) —
если клиент переподключился и снова открыл сокет с тем же токеном, комната продолжает
жить молча. Если нет — комната закрывается с `end_reason=timeout`, партнёр получает
`partner_left { reason: "timeout" }`.
