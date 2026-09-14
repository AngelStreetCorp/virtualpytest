export interface WebElement {
  index: number;
  tagName: string;
  selector: string;
  textContent: string;
  attributes: Record<string, any>;
  position: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
  isVisible: boolean;
  className: string;
  id: string | null;
}

export interface WebDumpResult {
  success: boolean;
  elements: WebElement[];
  summary: {
    total_count: number;
    visible_count: number;
    page_title: string;
    page_url: string;
    viewport: {
      width: number;
      height: number;
    };
  };
}
