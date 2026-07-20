import type { Chat, Message } from "../types/chat";
import type {
  ChatProvider,
  RegenerateMessageResult,
  SendMessageResult,
} from "./chatProvider";

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

const createId = () =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2);

const BOARD_SUMMARY_CARD = `<!-- lore-card: {
  "fileName": "board_summary_q3.pdf",
  "runLabel": "Запуск 15.07.2026 09:42",
  "title": "Сравнить · Чанки 3 · Связанные данные 2 · Диагностика 3 · Замечания 2",
  "meta": "page 2 · table 2 · 37 токенов",
  "preview": "Таблица бюджета по каналам с прогнозом ROI и чувствительностью к снижению spend.",
  "columns": ["channel", "spend", "roi"],
  "rows": [
    { "channel": "Brand", "spend": "1.2M", "roi": 1.6 },
    { "channel": "Performance", "spend": "2.8M", "roi": 2.4 }
  ],
  "chunks": [
    {
      "meta": "page 1 · heading 1 · 42 токенов",
      "title": "Подготовка board summary",
      "preview": "- Рост MRR +12% - Решение по перераспределению бюджета"
    },
    {
      "meta": "page 2 · table 2 · 37 токенов",
      "title": "Таблица бюджета по каналам с прогнозом ROI и чувствительностью к снижению spend.",
      "preview": "Таблица бюджета по каналам с прогнозом ROI и чувствительностью к снижению spend.",
      "columns": ["channel", "spend", "roi"],
      "rows": [
        { "channel": "Brand", "spend": "1.2M", "roi": 1.6 },
        { "channel": "Performance", "spend": "2.8M", "roi": 2.4 }
      ]
    },
    {
      "meta": "page 3 · figure 3 · 25 токенов",
      "title": "Revenue bridge",
      "figureLabel": "Заявка -> Руководитель -> HR -> Активация"
    }
  ]
} -->`;

const chunkText = async function* (text: string) {
  let current = "";

  for (const word of text.split(" ")) {
    current = current ? `${current} ${word}` : word;
    yield current;
    await delay(65);
  }
};

const initialChats: Chat[] = [
  {
    id: "chat-1",
    title: "Утренний дайджест",
    description: "Сформировали автоматический текст по дашборду на каждое утро.",
    time: "Вчера",
  },
  {
    id: "chat-2",
    title: "Обзор критичных рисков",
    description: "Сводить продуктовые и data-риски в один список для эскалации.",
    time: "18:10",
  },
  {
    id: "chat-3",
    title: "Новая задача",
    description: "Новая задача создана и готова к обсуждению.",
    time: "Только что",
  },
  {
    id: "chat-4",
    title: "Подготовка board summary",
    description: "Собрать сводку по росту, блокерам и решениям для обзора.",
    time: "15:00",
  },
  {
    id: "chat-5",
    title: "Апдейт для борда",
    description: "Суммировали рост выручки, риски и аномалии недели.",
    time: "11:48",
  },
  {
    id: "chat-6",
    title: "Сценарий для CEO sync",
    description: "Готовили короткую линию разговора для синка с CEO.",
    time: "09:54",
  },
];

const initialMessages: Record<string, Message[]> = {
  "chat-1": [],
  "chat-2": [],
  "chat-3": [],
  "chat-4": [
    {
      id: "m-1",
      chatId: "chat-4",
      role: "assistant",
      content:
        "Decision point: либо перераспределяем бюджет в более предсказуемые каналы уже сейчас, либо даём одной рискованной зоне ещё короткое окно на проверку гипотез.",
      status: "completed",
    },
    {
      id: "m-2",
      chatId: "chat-4",
      role: "user",
      content: 'Как сократить "Подготовка board summary" до одного экрана для руководителя?',
      status: "completed",
    },
    {
      id: "m-3",
      chatId: "chat-4",
      role: "assistant",
      content:
        'Оставить только изменение, риск и решение. Для "Подготовка board summary" этого достаточно, чтобы статус был управленческим, а не описательным.',
      status: "completed",
    },
    {
      id: "m-4",
      chatId: "chat-4",
      role: "user",
      content: "Что здесь лучше не перегружать деталями?",
      status: "completed",
    },
    {
      id: "m-5",
      chatId: "chat-4",
      role: "assistant",
      content:
        'Не перегружать внутренними срезами, если они не меняют решение. По задаче "Подготовка board summary" важно ускорить понимание, а не показать весь хвост анализа.',
      status: "completed",
    },
  ],
  "chat-5": [],
  "chat-6": [],
};

const mockReplies = [
  `Сделаю короткую управленческую версию: что изменилось, какой риск возник и какое решение нужно от руководителя.

${BOARD_SUMMARY_CARD}

Во второй плашке можно показать контекст решения: почему рост важен сейчас и что нужно подтвердить следующим шагом.`,
  `Для экрана руководителя лучше убрать второстепенные метрики и оставить только те факторы, которые двигают решение.

${BOARD_SUMMARY_CARD}

Такой ответ уже содержит svg внутри assistant-сообщения и открывает вторую плашку по клику.`,
  `Я бы собрал ответ в три строки: сигнал, интерпретация, следующий шаг.

${BOARD_SUMMARY_CARD}

Вторая плашка в модалке может объяснять сигнал человеческим языком без перегруза цифрами.`,
  `Если нужна версия для board, полезно добавить одно конкретное действие и срок.

${BOARD_SUMMARY_CARD}

Тогда первая плашка показывает визуальный акцент, а вторая помогает быстро принять решение.`,
];

export class MockChatProvider implements ChatProvider {
  private chats = [...initialChats];

  private messages = structuredClone(initialMessages);

  async getChats() {
    return [...this.chats];
  }

  async getMessages(chatId: string) {
    return [...(this.messages[chatId] ?? [])];
  }

  async createChat() {
    const chat: Chat = {
      id: createId(),
      title: "Новый чат",
      description: "Новый диалог для обсуждения.",
      time: "Только что",
    };

    this.chats = [chat, ...this.chats];
    this.messages[chat.id] = [];

    return chat;
  }

  async sendMessage(chatId: string, content: string): Promise<SendMessageResult> {
    const userMessage: Message = {
      id: createId(),
      chatId,
      role: "user",
      content,
      status: "completed",
    };

    const assistantMessage: Message = {
      id: createId(),
      chatId,
      role: "assistant",
      content: "",
      status: "streaming",
    };

    this.messages[chatId] = [
      ...(this.messages[chatId] ?? []),
      userMessage,
      assistantMessage,
    ];

    this.updateChat(chatId, content);

    const reply =
      mockReplies[Math.floor(Math.random() * mockReplies.length)] +
      " При необходимости могу сразу переписать это в формат для board slide.";

    return {
      userMessage,
      assistantMessage,
      stream: chunkText(reply),
    };
  }

  async regenerateMessage(
    chatId: string,
    assistantMessageId: string,
  ): Promise<RegenerateMessageResult> {
    const assistantMessage: Message = {
      id: createId(),
      chatId,
      role: "assistant",
      content: "",
      status: "streaming",
    };

    const reply =
      `Переформулирую короче: оставьте только главный сигнал, одно последствие для бизнеса и точечный запрос к руководителю.

${BOARD_SUMMARY_CARD}

Этого достаточно, чтобы разговор оставался управленческим, а деталь ушла во вторую плашку.`;

    return {
      assistantMessage,
      replaceMessageId: assistantMessageId,
      stream: chunkText(reply),
    };
  }

  private updateChat(chatId: string, content: string) {
    this.chats = this.chats.map((chat) =>
      chat.id === chatId
        ? {
            ...chat,
            title:
              chat.title === "Новый чат"
                ? content.slice(0, 34) || "Новый чат"
                : chat.title,
            description: content.slice(0, 72),
            time: "Только что",
          }
        : chat,
    );
  }
}
