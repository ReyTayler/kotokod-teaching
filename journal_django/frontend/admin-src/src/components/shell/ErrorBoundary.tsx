import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props { children: ReactNode }
interface State { hasError: boolean }

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[admin] render error:', error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="error-fallback">
          <h2 className="error-fallback__title">Что-то пошло не так</h2>
          <p className="error-fallback__text">Страница не отрисовалась. Попробуйте перезагрузить.</p>
          <button
            type="button"
            className="btn-save error-fallback__btn"
            onClick={() => window.location.reload()}
          >
            Перезагрузить
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
