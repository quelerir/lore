import { createContext, useContext } from "react";

export const SearchHighlightContext = createContext("");

export const useSearchHighlightQuery = () => useContext(SearchHighlightContext);

const escapeRegExp = (value: string) =>
  value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

export function renderHighlightedText(
  text: string,
  query: string,
  className: string,
) {
  const trimmed = query.trim();
  if (!trimmed) return text;

  const parts = text.split(new RegExp(`(${escapeRegExp(trimmed)})`, "gi"));
  if (parts.length === 1) return text;

  return parts.map((part, index) =>
    part.toLowerCase() === trimmed.toLowerCase() ? (
      <mark key={`${part}-${index}`} className={className}>
        {part}
      </mark>
    ) : (
      part
    ),
  );
}
