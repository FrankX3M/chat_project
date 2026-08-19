import React, { useMemo } from 'react';
import styles from './SettingsForm.module.css';
import {
  AGE_RANGE_LABELS,
  ALL_AGE_RANGES,
  AgeRange,
  ChatSettings,
  CRITERION_LABELS,
  Criterion,
  GENDER_LABELS,
  Gender,
  TOPICS_WITHOUT_ANY_GENDER,
  TOPICS_WITH_MULTI_AGE,
  TOPIC_LABELS,
  Topic,
  defaultSettingsForTopic,
} from '../shared/types';

export interface SettingsFormProps {
  settings: ChatSettings;
  onChange: (next: ChatSettings) => void;
  onlineCount: number;
  onStart: () => void;
}

const TOPIC_ORDER: Topic[] = ['general', 'flirt', 'roleplay'];

/**
 * Формa настроек перед поиском собеседника.
 *
 * Реализованные пункты ТЗ (task190826_v2):
 *  1. Во вкладках "Ролка" и "Флирт" убран пол "Неважно" (и свой, и
 *     собеседника) — см. genderOptionsFor().
 *  2. Во вкладках "Общение" и "Флирт" фильтр возраста собеседника — это
 *     набор чипов с множественным выбором, минимум один активен всегда.
 */
export function SettingsForm({
  settings,
  onChange,
  onlineCount,
  onStart,
}: SettingsFormProps) {
  const genderOptions = useMemo(
    () => genderOptionsFor(settings.topic),
    [settings.topic],
  );
  const showMultiAge = TOPICS_WITH_MULTI_AGE.has(settings.topic);
  const showCriterion = settings.topic === 'roleplay';

  function handleTopicChange(topic: Topic) {
    onChange(defaultSettingsForTopic(topic, settings));
  }

  function handleOwnGenderChange(gender: Gender) {
    onChange({ ...settings, ownGender: gender });
  }

  function handlePartnerGenderChange(gender: Gender) {
    onChange({ ...settings, partnerGender: gender });
  }

  function handleCriterionChange(criterion: Criterion) {
    onChange({ ...settings, criterion });
  }

  function handleColorThemeChange(colorTheme: 'light' | 'dark') {
    onChange({ ...settings, colorTheme });
  }

  /**
   * Задача 2: тумблер чипа. Если это последний выбранный возраст —
   * снять выбор нельзя (минимум одна вкладка возраста должна быть активна).
   */
  function toggleAgeRange(age: AgeRange) {
    const isActive = settings.partnerAgeRanges.includes(age);
    if (isActive) {
      if (settings.partnerAgeRanges.length === 1) {
        return;
      }
      onChange({
        ...settings,
        partnerAgeRanges: settings.partnerAgeRanges.filter((a) => a !== age),
      });
    } else {
      onChange({
        ...settings,
        partnerAgeRanges: [...settings.partnerAgeRanges, age],
      });
    }
  }

  return (
    <div className={styles.card}>
      <h1 className={styles.title}>Анонимный чат</h1>

      <div className={styles.section}>
        <div className={styles.sectionLabel}>Тема общения:</div>
        <div className={styles.topicRow}>
          {TOPIC_ORDER.map((topic) => (
            <button
              key={topic}
              type="button"
              className={[
                styles.option,
                settings.topic === topic ? styles.optionActive : '',
              ].join(' ')}
              onClick={() => handleTopicChange(topic)}
            >
              {TOPIC_LABELS[topic]}
            </button>
          ))}
        </div>
      </div>

      <div className={[styles.section, styles.row].join(' ')}>
        <div>
          <div className={styles.sectionLabel}>Ваш пол:</div>
          <div className={styles.optionGroup}>
            {genderOptions.map((gender) => (
              <button
                key={gender}
                type="button"
                className={[
                  styles.option,
                  settings.ownGender === gender ? styles.optionActive : '',
                ].join(' ')}
                onClick={() => handleOwnGenderChange(gender)}
              >
                {GENDER_LABELS[gender]}
              </button>
            ))}
          </div>
        </div>
        <div>
          <div className={styles.sectionLabel}>Пол собеседника:</div>
          <div className={styles.optionGroup}>
            {genderOptions.map((gender) => (
              <button
                key={gender}
                type="button"
                className={[
                  styles.option,
                  settings.partnerGender === gender
                    ? styles.optionActive
                    : '',
                ].join(' ')}
                onClick={() => handlePartnerGenderChange(gender)}
              >
                {GENDER_LABELS[gender]}
              </button>
            ))}
          </div>
        </div>
      </div>

      {showMultiAge && (
        <div className={styles.section}>
          <div className={styles.sectionLabel}>Возраст собеседника:</div>
          <div className={styles.ageChips}>
            {ALL_AGE_RANGES.map((age) => (
              <button
                key={age}
                type="button"
                className={[
                  styles.ageChip,
                  settings.partnerAgeRanges.includes(age)
                    ? styles.ageChipActive
                    : '',
                ].join(' ')}
                aria-pressed={settings.partnerAgeRanges.includes(age)}
                onClick={() => toggleAgeRange(age)}
              >
                {AGE_RANGE_LABELS[age]}
              </button>
            ))}
          </div>
          <div className={styles.ageHint}>Можно выбрать несколько — минимум один вариант</div>
        </div>
      )}

      {showCriterion && (
        <div className={styles.section}>
          <div className={styles.sectionLabel}>Критерий:</div>
          <div className={styles.optionGroup}>
            {(Object.keys(CRITERION_LABELS) as Criterion[]).map(
              (criterion) => (
                <button
                  key={criterion}
                  type="button"
                  className={[
                    styles.option,
                    settings.criterion === criterion
                      ? styles.optionActive
                      : '',
                  ].join(' ')}
                  onClick={() => handleCriterionChange(criterion)}
                >
                  {CRITERION_LABELS[criterion]}
                </button>
              ),
            )}
          </div>
        </div>
      )}

      <div className={styles.section}>
        <div className={styles.sectionLabel}>Цветовая схема:</div>
        <div className={styles.optionGroup}>
          <button
            type="button"
            className={[
              styles.option,
              settings.colorTheme === 'light' ? styles.optionActive : '',
            ].join(' ')}
            onClick={() => handleColorThemeChange('light')}
          >
            Светлая
          </button>
          <button
            type="button"
            className={[
              styles.option,
              settings.colorTheme === 'dark' ? styles.optionActive : '',
            ].join(' ')}
            onClick={() => handleColorThemeChange('dark')}
          >
            Тёмная
          </button>
        </div>
      </div>

      <button type="button" className={styles.startButton} onClick={onStart}>
        Начать чат
      </button>

      <div className={styles.onlineCounter}>
        Находятся в чате: <strong>{onlineCount}</strong> пользовател
        {pluralUsersSuffix(onlineCount)}
      </div>
    </div>
  );
}

/** Задача 1: для "Ролка" и "Флирт" вариант "Неважно" не показывается. */
function genderOptionsFor(topic: Topic): Gender[] {
  const all: Gender[] = ['any', 'male', 'female'];
  if (TOPICS_WITHOUT_ANY_GENDER.has(topic)) {
    return all.filter((g) => g !== 'any');
  }
  return all;
}

function pluralUsersSuffix(count: number): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return 'ь';
  if ([2, 3, 4].includes(mod10) && ![12, 13, 14].includes(mod100)) return 'я';
  return 'ей';
}
