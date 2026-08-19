import React, { useEffect, useRef } from 'react';
import styles from './EmojiPicker.module.css';

export interface EmojiPickerProps {
  emojis: string[];
  onPick: (emoji: string) => void;
  onClose: () => void;
}

/**
 * Задача 4: раньше окно смайликов закрывалось после выбора каждого —
 * теперь оно остаётся открытым, и можно добавить в сообщение сколько
 * угодно смайликов подряд. Закрывается явно (крестик/клик вне окна/Esc),
 * а не автоматически после mousedown/click по эмодзи.
 */
export function EmojiPicker({ emojis, onPick, onClose }: EmojiPickerProps) {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        onClose();
      }
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        onClose();
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [onClose]);

  return (
    <div className={styles.popover} ref={ref} role="dialog" aria-label="Смайлики">
      <div className={styles.header}>
        <span className={styles.headerLabel}>Смайлики</span>
        <button
          type="button"
          className={styles.closeButton}
          aria-label="Закрыть"
          onClick={onClose}
        >
          ×
        </button>
      </div>
      <div className={styles.grid}>
        {emojis.map((emoji) => (
          <button
            key={emoji}
            type="button"
            className={styles.emojiButton}
            // NB: намеренно НЕ вызываем onClose() здесь — это и есть
            // фикс задачи 4, окно остаётся открытым для повторного выбора.
            onClick={() => onPick(emoji)}
          >
            {emoji}
          </button>
        ))}
      </div>
    </div>
  );
}
