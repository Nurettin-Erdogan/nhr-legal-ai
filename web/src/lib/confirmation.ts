export interface ConfirmOptions {
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
}

export type PendingConfirmation = ConfirmOptions & { resolve: (ok: boolean) => void };
let show: ((request: PendingConfirmation) => void) | null = null;

export function confirmAction(options: ConfirmOptions): Promise<boolean> {
  if (!show) return Promise.resolve(false);
  return new Promise((resolve) => show?.({ ...options, resolve }));
}

export function registerConfirmationHost(
  handler: (request: PendingConfirmation) => void,
): () => void {
  show = handler;
  return () => {
    if (show === handler) show = null;
  };
}
