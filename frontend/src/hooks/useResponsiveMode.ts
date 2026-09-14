import { useMediaQuery, useTheme } from '@mui/material';
import { useState, useLayoutEffect } from 'react';

export type ResponsiveMode = 'mobile' | 'tablet' | 'desktop';

export const useResponsiveMode = () => {
  const theme = useTheme();
  
  // Try MUI's useMediaQuery first
  const muiIsMobile = useMediaQuery('(max-width:767px)');
  const muiIsTablet = useMediaQuery('(min-width:768px) and (max-width:1199px)');
  const muiIsDesktop = useMediaQuery('(min-width:1200px)');
  
  // Use state with SSR-safe initial value (assume mobile/tablet for initial render to avoid mismatch)
  // The actual value will be corrected on client after hydration
  const [windowWidth, setWindowWidth] = useState<number | undefined>(undefined);
  
  useLayoutEffect(() => {
    // Set initial width immediately during layout phase
    setWindowWidth(window.innerWidth);
    
    const handleResize = () => {
      setWindowWidth(window.innerWidth);
    };
    
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);
  
  // Use direct window width check if available, otherwise fall back to MUI
  // If windowWidth is undefined (SSR/hydration), use MUI's result
  // If windowWidth is available, use it directly for more reliable detection
  const isMobile = windowWidth !== undefined 
    ? windowWidth <= 767 
    : muiIsMobile;
  const isTablet = windowWidth !== undefined 
    ? windowWidth >= 768 && windowWidth <= 1199 
    : muiIsTablet;
  const isDesktop = windowWidth !== undefined 
    ? windowWidth >= 1200 
    : muiIsDesktop;

  const mode: ResponsiveMode = isMobile ? 'mobile' : isTablet ? 'tablet' : 'desktop';

  return {
    mode,
    isMobile,
    isTablet,
    isDesktop,
    theme,
  };
};
