import type { ChatProvider } from "./chatProvider";
import { ChainlitChatProvider } from "./chainlitChatProvider";
import { MockChatProvider } from "./mockChatProvider";

const providerType = import.meta.env.VITE_CHAT_PROVIDER ?? "mock";
const chainlitUrl = import.meta.env.VITE_CHAINLIT_URL ?? "http://localhost:8000";

export const chatProvider: ChatProvider =
  providerType === "chainlit"
    ? new ChainlitChatProvider(chainlitUrl)
    : new MockChatProvider();
