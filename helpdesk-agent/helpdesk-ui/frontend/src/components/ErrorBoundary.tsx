import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  message: string;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, message: "" };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, message: error.message };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // eslint-disable-next-line no-console
    console.error("ErrorBoundary caught", error, info);
  }

  render(): ReactNode {
    if (!this.state.hasError) return this.props.children;
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 p-8 text-center">
        <h1 className="text-xl font-semibold text-fg">Something went wrong.</h1>
        <p className="max-w-md text-sm text-fg-muted">{this.state.message}</p>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="rounded bg-surface-2 px-4 py-2 text-sm hover:bg-surface-2"
        >
          Reload page
        </button>
      </div>
    );
  }
}
