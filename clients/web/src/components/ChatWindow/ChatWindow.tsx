import React, { useState } from 'react';
import styles from './ChatWindow.module.css';
import { EmojiPicker } from './EmojiPicker';
import { ConfirmModal } from '../shared/ConfirmModal';
import { ChatMessage } from './ChatWindow.types';

const DEFAULT_EMOJIS = [
  '😀', '😂', '😍', '😉', '😢', '😡',
  '👍', '👎', '🔥', '💯', '🎉', '🙏',
  '💬', '❤️', '💛', '💜', '🤝', '👋',
];

export interface ChatWindowProps {
  messages: ChatMessage[];
  onlineCount: number;
  /**
   * Исходный обработчик кнопки "Далее" (leave + сразу следующий поиск).
   * Функционал не меняется — меняется только подпись кнопки и то, что
   * теперь перед вызовом показывается подтверждение (задача 6).
   */
  onNext: () => void;
  /**
   * Исходный обработчик кнопки "Стоп" (leave, без авто-перезапуска поиска).
   * Функционал не меняется, меняется только подпись кнопки на
   * "Настроить параметры".
   */
  onStop: () => void;
  /** MVP: жалоба = завершение чата, без отдельного REST-вызова /reports. */
  onReportAndEndChat: () => void;
  onSendMessage: (content: string) => void;
}

/**
 * Окно активного чата.
 *
 * Реализованные пункты ТЗ (task190826_v2):
 *  3. Кнопка "Далее" → "Завершить чат"; кнопка "Стоп" → "Настроить
 *     параметры". Обработчики (onNext/onStop) не меняются, меняются
 *     только подписи — см. комментарии у пропсов выше.
 *  4. Смайлики: EmojiPicker теперь не закрывается при выборе — см.
 *     EmojiPicker.tsx и handlePickEmoji ниже (окно закрывает только
 *     явное действие пользователя).
 *  5. Кнопка-красный треугольник → открывает подтверждение "Завершить
 *     чат и Пожаловаться?"; в рамках MVP просто завершает чат
 *     (onReportAndEndChat), без отдельного пайплайна модерации.
 *  6. Клик по "Завершить чат" сначала показывает предупреждение
 *     "у вас открыт активный чат, точно завершить?" и только после
 *     подтверждения вызывает исходный onNext().
 */
export function ChatWindow({
  messages,
  onlineCount,
  onNext,
  onStop,
  onReportAndEndChat,
  onSendMessage,
}: ChatWindowProps) {
  const [draft, setDraft] = useState('');
  const [isEmojiPickerOpen, setEmojiPickerOpen] = useState(false);
  const [isEndChatConfirmOpen, setEndChatConfirmOpen] = useState(false);
  const [isReportConfirmOpen, setReportConfirmOpen] = useState(false);

  function handlePickEmoji(emoji: string) {
    // Задача 4: добавляем эмодзи в черновик сообщения и НЕ закрываем
    // попап — пользователь может выбрать ещё сколько угодно смайликов.
    setDraft((prev) => prev + emoji);
  }

  function handleSend() {
    const trimmed = draft.trim();
    if (!trimmed) return;
    onSendMessage(trimmed);
    setDraft('');
  }

  function handleSendKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Enter') {
      handleSend();
    }
  }

  // Задача 6.
  function handleEndChatConfirmed() {
    setEndChatConfirmOpen(false);
    onNext();
  }

  // Задача 5.
  function handleReportConfirmed() {
    setReportConfirmOpen(false);
    onReportAndEndChat();
  }

  return (
    <div className={styles.card}>
      <div className={styles.header}>
        <span className={styles.onlineCounter}>
          Находятся в чате: <strong>{onlineCount}</strong>
        </span>
        {/* Задача 5: кнопка-красный треугольник ("Пожаловаться"). */}
        <button
          type="button"
          className={styles.reportTriangle}
          aria-label="Пожаловаться"
          onClick={() => setReportConfirmOpen(true)}
        >
          <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
            <path d="M12 3 22 20 2 20 Z" fill="currentColor" />
          </svg>
        </button>
      </div>

      <div className={styles.messages}>
        {messages.map((message) => (
          <div
            key={message.id}
            className={[
              styles.messageRow,
              message.sender === 'me' ? styles.messageRowMe : '',
              message.sender === 'system' ? styles.messageRowSystem : '',
            ].join(' ')}
          >
            <span className={styles.messageBubble}>{message.content}</span>
          </div>
        ))}
      </div>

      <div className={styles.inputRow}>
        <div className={styles.emojiAnchor}>
          <button
            type="button"
            className={styles.emojiTrigger}
            aria-label="Смайлики"
            onClick={() => setEmojiPickerOpen((v) => !v)}
          >
            🙂
          </button>
          {isEmojiPickerOpen && (
            <EmojiPicker
              emojis={DEFAULT_EMOJIS}
              onPick={handlePickEmoji}
              onClose={() => setEmojiPickerOpen(false)}
            />
          )}
        </div>
        <input
          type="text"
          className={styles.textInput}
          placeholder="Введите сообщение..."
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={handleSendKeyDown}
        />
        <button type="button" className={styles.sendButton} onClick={handleSend}>
          Отправить
        </button>
      </div>

      <div className={styles.footerButtons}>
        {/* Задача 3: было "Далее" — теперь "Завершить чат". */}
        <button
          type="button"
          className={[styles.footerButton, styles.footerButtonPrimary].join(' ')}
          onClick={() => setEndChatConfirmOpen(true)}
        >
          Завершить чат
        </button>
        {/* Задача 3: было "Стоп" — теперь "Настроить параметры". */}
        <button
          type="button"
          className={[styles.footerButton, styles.footerButtonDanger].join(' ')}
          onClick={onStop}
        >
          Настроить параметры
        </button>
      </div>

      {isEndChatConfirmOpen && (
        <ConfirmModal
          title="У вас открыт активный чат"
          description="Точно ли хотите завершить текущий чат?"
          confirmLabel="Да"
          cancelLabel="Нет"
          confirmTone="orange"
          onConfirm={handleEndChatConfirmed}
          onCancel={() => setEndChatConfirmOpen(false)}
        />
      )}

      {isReportConfirmOpen && (
        <ConfirmModal
          title="Завершить чат и Пожаловаться?"
          description={
            <>
              Вы уверены, что хотите <strong>завершить чат и пожаловаться</strong>{' '}
              на собеседника?
            </>
          }
          confirmLabel="Завершить"
          cancelLabel="Отменить"
          confirmTone="orange"
          onConfirm={handleReportConfirmed}
          onCancel={() => setReportConfirmOpen(false)}
        />
      )}
    </div>
  );
}
