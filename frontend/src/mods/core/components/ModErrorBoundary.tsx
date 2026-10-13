import React from 'react';

interface Props {
  slot: string;
  fallback: React.ReactNode;
  children: React.ReactNode;
}

interface State {
  failed: boolean;
}

/** A mod tree that throws while drawn costs its slot alone: the default is drawn instead. */
export class ModErrorBoundary extends React.Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error) {
    console.warn(`[@mods] ${this.props.slot} threw while drawn; the default is drawn instead`, error);
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}
