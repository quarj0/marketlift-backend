# Marketlift realtime transport

Marketlift uses one authenticated WebSocket per signed-in browser session:

- `ws://<api-host>/ws/realtime/` in local development
- `wss://<api-host>/ws/realtime/` in production

The socket uses the existing Django session cookie through Channels' authentication middleware. The ASGI application validates the WebSocket `Origin` against `MARKETLIFT_WEBSOCKET_ALLOWED_ORIGINS`.

## Responsibilities

GraphQL remains the durable API for conversation creation, history/pagination, notification history, and recovery after reconnects. The WebSocket carries live commands and events:

Client commands:

- `ping`
- `message.send`
- `conversation.read`
- `notification.read`
- `notification.read_all`

Server events:

- `realtime.ready`
- `message.created`
- `conversation.read`
- `notification.created`
- `notification.read`
- `notification.read_all`
- `command.ack`
- `error`
- `pong`

On connection, `realtime.ready` includes the current unread message and notification counts. This lets the frontend recover correct counters after a disconnect; database state remains the source of truth and Redis/WebSockets are delivery mechanisms only.

## Examples

Send a text message:

```json
{
  "type": "message.send",
  "requestId": "client-123",
  "conversationId": "<uuid>",
  "text": "Is this still available?"
}
```

Send an uploaded image:

```json
{
  "type": "message.send",
  "conversationId": "<uuid>",
  "text": "",
  "uploadId": "<completed-message-image-upload-uuid>"
}
```

Mark a conversation read:

```json
{"type":"conversation.read","conversationId":"<uuid>"}
```

Mark one notification read:

```json
{"type":"notification.read","notificationId":"<uuid>"}
```

## Infrastructure

`channels_redis` is configured by `CHANNEL_REDIS_URL`. This is independent from the database provider and object-storage provider. A local Docker Redis instance can be used in development, while production may use any compatible shared Redis endpoint.
