import { useEffect, useRef, useState } from 'react';

export interface ElementBox {
  width: number;
  height: number;
  x: number;
  y: number;
}

/** Live size + page position of an element (ResizeObserver); null until first measured. */
export const useElementBox = <T extends HTMLElement>() => {
  const ref = useRef<T | null>(null);
  const [box, setBox] = useState<ElementBox | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const measure = () => {
      const r = el.getBoundingClientRect();
      setBox({ width: Math.round(r.width), height: Math.round(r.height), x: Math.round(r.left), y: Math.round(r.top) });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return { ref, box };
};
