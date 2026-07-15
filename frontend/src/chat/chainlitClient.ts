import { ChainlitAPI } from "@chainlit/react-client";

const baseUrl: string =
  import.meta.env.VITE_CHAINLIT_URL ?? "http://localhost:8000";

let on401: (() => void) | undefined;

export const setOn401 = (cb: () => void) => {
  on401 = cb;
};

export const chainlitApi = new ChainlitAPI(baseUrl, "webapp", undefined, () =>
  on401?.(),
);
