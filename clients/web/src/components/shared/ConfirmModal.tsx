import React from 'react';
import styles from './ConfirmModal.module.css';

export interface ConfirmModalProps {
  title: string;
  description: React.ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  /** Цвет акцентной (confirm) кнопки — под сценарий диалога. */
  confirmTone?: 'orange' | 'red' | 'green';
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * Универсальное модальное окно-предупреждение, переиспользуется для:
 *  - задачи 5: "Завершить чат и Пожаловаться?" (красный треугольник в чате)
 *  - задачи 6: "У вас открыт активный чат, точно завершить?" (кнопка
 *    "Завершить чат")
 */
export function ConfirmModal({
  title,
  description,
  confirmLabel,
  cancelLabel = 'Отменить',
  confirmTone = 'orange',
  onConfirm,
  onCancel,
}: ConfirmModalProps) {
  return (
    <div
      className={styles.overlay}
      role="presentation"
      onClick={onCancel}
    >
      <div
        className={styles.dialog}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-modal-title"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          className={styles.closeButton}
          aria-label="Закрыть"
          onClick={onCancel}
        >
          ×
        </button>
        <div className={styles.icon}>?</div>
        <h2 id="confirm-modal-title" className={styles.title}>
          {title}
        </h2>
        <p className={styles.description}>{description}</p>
        <div className={styles.actions}>
          <button
            type="button"
            className={[styles.actionButton, styles.actionGreen].join(' ')}
            onClick={onCancel}
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            className={[
              styles.actionButton,
              confirmTone === 'red'
                ? styles.actionRed
                : confirmTone === 'green'
                ? styles.actionGreen
                : styles.actionOrange,
            ].join(' ')}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
