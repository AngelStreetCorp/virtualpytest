/** One-line description and key page per endpoint preset (static; unknown presets show nothing). */
export interface PresetInfo {
  description: string;
  keyUrl?: string;
}

export const PRESET_INFO: Record<string, PresetInfo> = {
  anthropic: { description: 'Claude models, direct from Anthropic.', keyUrl: 'https://console.anthropic.com/settings/keys' },
  openrouter: { description: 'One key for many providers, with live web search.', keyUrl: 'https://openrouter.ai/keys' },
  openai: { description: 'GPT models from OpenAI.', keyUrl: 'https://platform.openai.com/api-keys' },
  minimax: { description: 'MiniMax models on the flat coding plan.', keyUrl: 'https://platform.minimax.io/user-center/basic-information/interface-key' },
  google: { description: 'Gemini models from Google, with grounded search.', keyUrl: 'https://aistudio.google.com/apikey' },
  minimax_vlm: { description: 'MiniMax image description (coding plan): one image plus a prompt in, text out.', keyUrl: 'https://platform.minimax.io/user-center/basic-information/interface-key' },
  openai_compatible: { description: 'Any local OpenAI-compatible server (LM Studio, Ollama, vLLM). No key needed.' },
};
