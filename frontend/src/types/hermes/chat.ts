/** POST /api/v1/chat/start response shape. */
export type HermesChatStartResult = {
  stream_id?: string;
  title?: string;
  effective_model?: string;
  effective_model_provider?: string | null;
  pending_started_at?: number;
};
