import React from 'react';

interface Props {
  children: React.ReactNode;
  /** Rendered in place of the subtree when it throws. */
  fallback: React.ReactNode;
  /** Identifies the boundary in logs. */
  label: string;
}

interface State {
  hasError: boolean;
}

/**
 * Without a boundary, a throw anywhere unmounts the whole React tree and the
 * page goes blank — which is exactly what a failed WebGL context used to do
 * here. Scoping a boundary around the 3D scene keeps the rest of the interface
 * alive when the GPU is unavailable.
 */
export default class ErrorBoundary extends React.Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error) {
    console.error(`[${this.props.label}] caught:`, error);
  }

  render() {
    return this.state.hasError ? this.props.fallback : this.props.children;
  }
}
