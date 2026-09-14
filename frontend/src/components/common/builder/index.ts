/**
 * Shared Builder Container Components
 * 
 * Container-based architecture: Each component provides ONLY the container styling,
 * accepting content as children. All styling matches TestCaseBuilder exactly.
 * 
 * Usage:
 * ```tsx
 * <BuilderPageLayout>
 *   <BuilderHeaderContainer actualMode={mode}>
 *     {/* Your custom header content *\/}
 *   </BuilderHeaderContainer>
 *   
 *   <BuilderMainContainer>
 *     <BuilderSidebarContainer actualMode={mode} isOpen={open} onToggle={toggle}>
 *       {/* Your custom sidebar content *\/}
 *     </BuilderSidebarContainer>
 *     {/* Canvas content *\/}
 *   </BuilderMainContainer>
 *   
 *   <BuilderStatsBarContainer actualMode={mode}>
 *     {/* Your custom stats content *\/}
 *   </BuilderStatsBarContainer>
 * </BuilderPageLayout>
 * ```
 */

export { BuilderPageLayout } from './BuilderPageLayout';
export { BuilderHeaderContainer } from './BuilderHeaderContainer';
export { BuilderSidebarContainer } from './BuilderSidebarContainer';
export { BuilderMainContainer } from './BuilderMainContainer';
export { BuilderStatsBarContainer } from './BuilderStatsBarContainer';
export { ToolboxSearchBox } from './ToolboxSearchBox';
export { DraggableCommand } from './DraggableCommand';
export { ToolboxMainTabs, type ToolboxMainTabValue } from './ToolboxMainTabs';
export { ToolboxAccordion, TOOLBOX_TAB_COLORS } from './ToolboxAccordion';
export { DraggableToolboxItem } from './DraggableToolboxItem';
export { BlockOutputHandles, getHandleColor, type OutputType } from './BlockOutputHandles';
