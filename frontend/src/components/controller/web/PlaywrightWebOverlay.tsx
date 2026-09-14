import React, { useEffect, useState, useMemo } from 'react';

import { PanelInfo } from '../../../types/controller/Panel_Types';
import { WebElement } from '../../../types/controller/Web_Types';
import { getZIndex } from '../../../utils/zIndexUtils';
import '../../../styles/webOverlayAnimations.css';

interface ScaledElement {
  selector: string;
  x: number;
  y: number;
  width: number;
  height: number;
  color: string;
  label: string;
  index: number;
}

interface PlaywrightWebOverlayProps {
  elements: WebElement[];
  isVisible: boolean;
  onElementClick?: (element: WebElement) => void;
  panelInfo: PanelInfo;
}

// Element highlight colors - using centralized theme
import { ELEMENT_HIGHLIGHT_COLORS } from '../../../constants/agentChatTheme';
const COLORS = ELEMENT_HIGHLIGHT_COLORS;

export const PlaywrightWebOverlay = React.memo(
  function PlaywrightWebOverlay({
    elements,
    isVisible,
    onElementClick,
    panelInfo,
  }: PlaywrightWebOverlayProps) {
    const [scaledElements, setScaledElements] = useState<ScaledElement[]>([]);
    const [clickAnimation, setClickAnimation] = useState<{
      x: number;
      y: number;
      id: string;
    } | null>(null);
    const [coordinateDisplay, setCoordinateDisplay] = useState<{
      x: number;
      y: number;
      id: string;
    } | null>(null);

    // Calculate actual content dimensions using contain logic (preserve aspect ratio)
    // This ensures overlay aligns with VNC stream content, not the panel container
    const { actualContentWidth, actualContentHeight, horizontalOffset, verticalOffset } = useMemo(() => {
      if (!panelInfo || !panelInfo.deviceResolution || !panelInfo.size) {
        return { actualContentWidth: 0, actualContentHeight: 0, horizontalOffset: 0, verticalOffset: 0 };
      }

      // Browser viewport dimensions
      const browserWidth = panelInfo.deviceResolution.width;
      const browserHeight = panelInfo.deviceResolution.height;

      // Use contain logic to match HLSVideoPlayer objectFit: 'contain'
      const browserAspectRatio = browserWidth / browserHeight;
      const panelAspectRatio = panelInfo.size.width / panelInfo.size.height;

      let actualWidth, actualHeight, hOffset, vOffset;

      if (browserAspectRatio <= panelAspectRatio) {
        // Browser is narrower than panel - fit by height
        actualHeight = panelInfo.size.height;
        actualWidth = actualHeight * browserAspectRatio;
        hOffset = (panelInfo.size.width - actualWidth) / 2;
        vOffset = 0;
      } else {
        // Browser is wider than panel - fit by width
        actualWidth = panelInfo.size.width;
        actualHeight = actualWidth / browserAspectRatio;
        hOffset = 0;
        vOffset = (panelInfo.size.height - actualHeight) / 2;
      }

      console.log('[PlaywrightWebOverlay] Contain scaling calculated:', {
        scalingMode: 'contain (preserve aspect ratio)',
        browserAspectRatio,
        panelAspectRatio,
        browserWidth,
        browserHeight,
        panelWidth: panelInfo.size.width,
        panelHeight: panelInfo.size.height,
        actualWidth,
        actualHeight,
        hOffset,
        vOffset,
      });

      return {
        actualContentWidth: actualWidth,
        actualContentHeight: actualHeight,
        horizontalOffset: hOffset,
        verticalOffset: vOffset,
      };
    }, [panelInfo]);

    // Calculate scaled elements for overlay positioning
    useEffect(() => {
      if (elements.length === 0) {
        setScaledElements([]);
        return;
      }

      // Skip calculation if panelInfo is not properly defined
      if (!panelInfo || !panelInfo.deviceResolution || !panelInfo.scaleX || !panelInfo.scaleY) {
        setScaledElements([]);
        return;
      }

      const scaled = elements
        .map((element, index) => {
          const getElementLabel = (el: WebElement) => {
            // Priority: aria-label → textContent → tagName + id
            if (el.attributes['aria-label']) {
              return el.attributes['aria-label'].substring(0, 20);
            } else if (el.textContent && el.textContent.trim()) {
              return `"${el.textContent.trim()}"`.substring(0, 20);
            } else {
              return `${el.tagName}${el.id ? '#' + el.id : ''}`.substring(0, 20);
            }
          };

          // Use individual scaleX and scaleY for accurate scaling
          // Browser elements coordinates * scale factors = overlay coordinates
          const scaleX = panelInfo.scaleX!;
          const scaleY = panelInfo.scaleY!;

          // Debug logging for first element
          if (index === 0) {
            console.log('[PlaywrightWebOverlay] ScaleX/ScaleY Scaling Debug:', {
              scaleX: scaleX,
              scaleY: scaleY,
              browserViewport: panelInfo.deviceResolution,
              overlaySize: panelInfo.size,
              originalElement: {
                x: element.position.x,
                y: element.position.y,
                width: element.position.width,
                height: element.position.height
              },
              scaledPosition: {
                x: element.position.x * scaleX,
                y: element.position.y * scaleY,
                width: element.position.width * scaleX,
                height: element.position.height * scaleY
              }
            });
          }

          const scaledElement = {
            selector: element.selector,
            x: element.position.x * scaleX + horizontalOffset,
            y: element.position.y * scaleY + verticalOffset,
            width: element.position.width * scaleX,
            height: element.position.height * scaleY,
            color: COLORS[index % COLORS.length],
            label: getElementLabel(element),
            index: element.index,
          };

          return scaledElement;
        })
        .filter(Boolean) as ScaledElement[];

      setScaledElements(scaled);
    }, [elements, panelInfo, horizontalOffset, verticalOffset]);

    // Handle element click
    const handleElementClick = async (scaledElement: ScaledElement, event: React.MouseEvent) => {
      event.stopPropagation();

      // Show click animation at element center
      const animationX = scaledElement.x + scaledElement.width / 2;
      const animationY = scaledElement.y + scaledElement.height / 2;
      const animationId = `element-${scaledElement.index}-${Date.now()}`;

      console.log(`[PlaywrightWebOverlay] Element click - Position: (${Math.round(animationX)}, ${Math.round(animationY)}), Selector: ${scaledElement.selector}`);

      setClickAnimation({ 
        x: animationX, 
        y: animationY, 
        id: animationId
      });

      // Set coordinate display for 2 seconds
      const coordDisplayId = `coord-${Date.now()}`;
      setCoordinateDisplay({
        x: animationX,
        y: animationY,
        id: coordDisplayId
      });

      // Clear animation after 300ms
      setTimeout(() => setClickAnimation(null), 300);
      
      // Clear coordinate display after 2 seconds
      setTimeout(() => setCoordinateDisplay(null), 2000);

      const originalElement = elements.find((el) => el.selector === scaledElement.selector);
      if (originalElement && onElementClick) {
        onElementClick(originalElement);
      }
    };

    // Handle base layer tap
    const handleBaseTap = async (event: React.MouseEvent) => {
      const rect = event.currentTarget.getBoundingClientRect();
      const contentX = event.clientX - rect.left;
      const contentY = event.clientY - rect.top;

      // Scale coordinates back to browser viewport space using individual scale factors
      const scaleX = panelInfo.scaleX!;
      const scaleY = panelInfo.scaleY!;
      const browserX = Math.round(contentX / scaleX);
      const browserY = Math.round(contentY / scaleY);

      console.log(`[PlaywrightWebOverlay] Base tap - Panel: (${Math.round(contentX)}, ${Math.round(contentY)}), Browser: (${browserX}, ${browserY}), ScaleX: ${scaleX.toFixed(3)}, ScaleY: ${scaleY.toFixed(3)}`);

      // Show click animation at tap location (in panel coordinates)
      const animationId = `base-tap-${Date.now()}`;
      setClickAnimation({ 
        x: contentX, 
        y: contentY, 
        id: animationId
      });

      // Set coordinate display for 2 seconds (show browser coordinates)
      const coordDisplayId = `coord-${Date.now()}`;
      setCoordinateDisplay({
        x: contentX,
        y: contentY,
        id: coordDisplayId
      });

      // Clear animation after 300ms
      setTimeout(() => setClickAnimation(null), 300);
      
      // Clear coordinate display after 2 seconds
      setTimeout(() => setCoordinateDisplay(null), 2000);
    };

    if (!isVisible) {
      return null;
    }

    return (
      <>
        {/* Base transparent tap layer - Aligned with VNC stream content */}
        <div
          style={{
            position: 'fixed',
            left: `${panelInfo.position.x + horizontalOffset}px`,
            top: `${panelInfo.position.y + verticalOffset}px`,
            width: `${actualContentWidth}px`,
            height: `${actualContentHeight}px`,
            zIndex: getZIndex('DEBUG_OVERLAY', 5), // Use higher z-index above VNC streams
            contain: 'layout style size',
            willChange: 'transform',
            pointerEvents: 'auto',
            border: '1px solid rgba(255, 0, 0, 0.3)', // Red border for web overlay
            cursor: 'crosshair',
          }}
          onClick={handleBaseTap}
        ></div>

        {/* Elements layer - Container positioned at panel origin */}
        {scaledElements.length > 0 && (
          <div
            style={{
              position: 'fixed',
              left: `${panelInfo.position.x}px`,
              top: `${panelInfo.position.y}px`,
              width: `${panelInfo.size.width}px`,
              height: `${panelInfo.size.height}px`,
              zIndex: getZIndex('DEBUG_OVERLAY', 5),
              contain: 'layout style size',
              willChange: 'transform',
              pointerEvents: 'none',
            }}
          >
            {/* Render scaled elements as colored rectangles */}
            {scaledElements.map((scaledElement) => (
              <div
                key={scaledElement.selector}
                style={{
                  position: 'absolute',
                  left: `${scaledElement.x}px`,
                  top: `${scaledElement.y}px`,
                  width: `${scaledElement.width}px`,
                  height: `${scaledElement.height}px`,
                  backgroundColor: `${scaledElement.color}1A`, // 10% transparency
                  border: `2px solid ${scaledElement.color}`,
                  pointerEvents: 'auto',
                  cursor: 'pointer',
                  overflow: 'hidden',
                  boxShadow: '0 2px 4px rgba(0, 0, 0, 0.3)',
                }}
                onClick={(event) => handleElementClick(scaledElement, event)}
                title={`${scaledElement.index}.${scaledElement.label} - ${scaledElement.selector}`}
              >
                {/* Element index in corner */}
                <div
                  style={{
                    position: 'absolute',
                    bottom: '2px',
                    right: '2px',
                    fontSize: '10px',
                    color: scaledElement.color,
                    fontWeight: 'bold',
                    lineHeight: '1',
                  }}
                >
                  {scaledElement.index}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Click animation */}
        {clickAnimation && (
          <div
            key={clickAnimation.id}
            style={{
              position: 'fixed',
              left: `${panelInfo.position.x + horizontalOffset + clickAnimation.x - 15}px`,
              top: `${panelInfo.position.y + verticalOffset + clickAnimation.y - 15}px`,
              width: '30px',
              height: '30px',
              borderRadius: '50%',
              backgroundColor: 'rgba(255, 255, 255, 0.8)',
              border: '2px solid rgba(255, 0, 0, 0.8)',
              zIndex: getZIndex('DEBUG_OVERLAY', 5),
              pointerEvents: 'none',
              animation: 'webClickPulse 0.3s ease-out forwards',
            }}
          />
        )}

        {/* Coordinate display */}
        {coordinateDisplay && (
          <div
            key={coordinateDisplay.id}
            style={{
              position: 'fixed',
              left: `${panelInfo.position.x + horizontalOffset + coordinateDisplay.x + 20}px`,
              top: `${panelInfo.position.y + verticalOffset + coordinateDisplay.y - 15}px`,
              backgroundColor: 'rgba(0, 0, 0, 0.8)',
              color: 'white',
              padding: '4px 8px',
              borderRadius: '4px',
              fontSize: '12px',
              fontFamily: 'monospace',
              fontWeight: 'bold',
              zIndex: getZIndex('DEBUG_OVERLAY', 5),
              pointerEvents: 'none',
              whiteSpace: 'nowrap',
            }}
          >
            Browser: {Math.round(coordinateDisplay.x / panelInfo.scaleX!)}, {Math.round(coordinateDisplay.y / panelInfo.scaleY!)}
          </div>
        )}
      </>
    );
  },
  (prevProps, nextProps) => {
    return (
      prevProps.elements === nextProps.elements &&
      prevProps.isVisible === nextProps.isVisible &&
      prevProps.onElementClick === nextProps.onElementClick &&
      JSON.stringify(prevProps.panelInfo) === JSON.stringify(nextProps.panelInfo)
    );
  },
);
