const isSameDay = (left: Date, right: Date) =>
  left.getFullYear() === right.getFullYear() &&
  left.getMonth() === right.getMonth() &&
  left.getDate() === right.getDate();

const getYesterday = (date: Date) => {
  const yesterday = new Date(date);
  yesterday.setDate(date.getDate() - 1);
  return yesterday;
};

const getStartOfDay = (date: Date) =>
  new Date(date.getFullYear(), date.getMonth(), date.getDate());

export const isToday = (date: Date, now = new Date()) => isSameDay(date, now);

export const isYesterday = (date: Date, now = new Date()) =>
  isSameDay(date, getYesterday(now));

const isWithinLast7Days = (date: Date, now = new Date()) => {
  const startOfToday = getStartOfDay(now);
  const startOfDate = getStartOfDay(date);
  const diffMs = startOfToday.getTime() - startOfDate.getTime();
  const diffDays = diffMs / 86400000;
  return diffDays >= 2 && diffDays <= 7;
};

const isThisMonth = (date: Date, now = new Date()) =>
  date.getFullYear() === now.getFullYear() && date.getMonth() === now.getMonth();

const isThisYear = (date: Date, now = new Date()) =>
  date.getFullYear() === now.getFullYear();

export const formatChatTime = (value: string | number, now = new Date()) => {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "";
  }

  const datePart = date.toLocaleDateString("ru-RU", {
    day: "numeric",
    month: "short",
  });
  const timePart = date.toLocaleTimeString("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
  });

  return `${datePart} в ${timePart}`;
};

export const getChatGroupMeta = (value: string | number, now = new Date()) => {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return { label: "Без даты", order: 9999999999999 };
  }

  if (isToday(date, now)) {
    return { label: "Сегодня", order: 0 };
  }

  if (isYesterday(date, now)) {
    return { label: "Вчера", order: 1 };
  }

  if (isWithinLast7Days(date, now)) {
    return { label: "Последние 7 дней", order: 2 };
  }

  if (isThisMonth(date, now)) {
    return { label: "Этот месяц", order: 3 };
  }

  if (isThisYear(date, now)) {
    return { label: "Этот год", order: 4 };
  }

  return {
    label: date.toLocaleDateString("ru-RU", {
      day: "numeric",
      month: "long",
    }),
    order: 5,
  };
};
