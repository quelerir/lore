export interface Chat {
  id: string;
  title: string;
  description: string;
  time: string;
}

export interface Message {
  id: string;
  chatId: string;
  role: "user" | "assistant";
  content: string;
  status?: "sending" | "streaming" | "completed" | "error";
}
