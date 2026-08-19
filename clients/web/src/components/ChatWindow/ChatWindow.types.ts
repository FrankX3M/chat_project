export interface ChatMessage {
  id: string;
  sender: 'me' | 'partner' | 'system';
  content: string;
  createdAt: string;
}

export type ReportReason =
  | 'spam'
  | 'harassment'
  | 'underage_suspicion'
  | 'illegal_content'
  | 'other';
