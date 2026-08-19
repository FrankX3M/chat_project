/**
 * Общие типы для настроек чата и UI-слоя (не влияет на серверный контракт,
 * см. server/app/schemas/settings.py и shared/openapi.json — при переносе
 * на бэкенд сверяться с ними, а не дублировать значения вручную).
 */

export type Topic = 'general' | 'flirt' | 'roleplay';

export const TOPIC_LABELS: Record<Topic, string> = {
  general: 'Общение',
  flirt: 'Флирт 18+',
  roleplay: 'Ролка',
};

/**
 * Задача 1: во вкладках "Ролка" и "Флирт" пол "Неважно"/"Не важно" убирается
 * — как для своего пола, так и для пола собеседника. Список тем, где
 * действует ограничение, вынесен в константу, чтобы не размазывать
 * условие по компоненту.
 */
export const TOPICS_WITHOUT_ANY_GENDER: ReadonlySet<Topic> = new Set([
  'flirt',
  'roleplay',
]);

export type Gender = 'any' | 'male' | 'female';

export const GENDER_LABELS: Record<Gender, string> = {
  any: 'Неважно',
  male: 'М',
  female: 'Ж',
};

/**
 * Задача 2: во вкладках "Общение" и "Флирт" фильтр возраста собеседника
 * становится множественным выбором (минимум одно значение). Для "Ролки"
 * фильтр возраста в текущем ТЗ не задействован — там своя логика
 * (критерий "Ищу сюжет" / "Предлагаю сюжет").
 */
export const TOPICS_WITH_MULTI_AGE: ReadonlySet<Topic> = new Set([
  'general',
  'flirt',
]);

export type AgeRange = '18-24' | '25-34' | '35-44' | '45+';

export const AGE_RANGE_LABELS: Record<AgeRange, string> = {
  '18-24': '18–24',
  '25-34': '25–34',
  '35-44': '35–44',
  '45+': '45+',
};

export const ALL_AGE_RANGES: AgeRange[] = ['18-24', '25-34', '35-44', '45+'];

export type Criterion = 'looking_for_plot' | 'offering_plot';

export const CRITERION_LABELS: Record<Criterion, string> = {
  looking_for_plot: 'Ищу сюжет',
  offering_plot: 'Предлагаю сюжет',
};

export type ColorTheme = 'light' | 'dark';

export interface ChatSettings {
  topic: Topic;
  ownGender: Gender;
  partnerGender: Gender;
  /** Актуально только когда topic ∈ TOPICS_WITH_MULTI_AGE. Минимум 1 элемент. */
  partnerAgeRanges: AgeRange[];
  /** Актуально только для topic === 'roleplay'. */
  criterion: Criterion;
  colorTheme: ColorTheme;
}

export function defaultSettingsForTopic(
  topic: Topic,
  prev?: Partial<ChatSettings>,
): ChatSettings {
  const ownGender = normalizeGenderForTopic(prev?.ownGender ?? 'any', topic);
  const partnerGender = normalizeGenderForTopic(
    prev?.partnerGender ?? 'any',
    topic,
  );
  return {
    topic,
    ownGender,
    partnerGender,
    partnerAgeRanges:
      prev?.partnerAgeRanges && prev.partnerAgeRanges.length > 0
        ? prev.partnerAgeRanges
        : ['18-24'],
    criterion: prev?.criterion ?? 'looking_for_plot',
    colorTheme: prev?.colorTheme ?? 'dark',
  };
}

/**
 * Если тема требует убрать "Неважно", а сохранённое значение было "any" —
 * приводим к дефолту 'male', чтобы не оставлять фильтр в невалидном
 * состоянии при переключении вкладок.
 */
export function normalizeGenderForTopic(
  gender: Gender,
  topic: Topic,
): Gender {
  if (gender === 'any' && TOPICS_WITHOUT_ANY_GENDER.has(topic)) {
    return 'male';
  }
  return gender;
}
