import { useEffect } from "react";

/** Sets `document.title` while the page is mounted (console pages get theirs from `ui/Page`). */
export function useDocumentTitle(title: string) {
  useEffect(() => { document.title = title; }, [title]);
}
