/**
 * Entity Detection Service
 *
 * Analyzes text (user prompts, AI responses) to detect mentions of:
 * - Devices (device names)
 * - Hosts (host names)
 * - UserInterfaces (UI names)
 * - TestCases (test case names)
 * - Campaigns (campaign names)
 *
 * Uses fuzzy matching and confidence scoring for smart detection.
 */

export interface DetectedEntities {
  device?: { id: string; confidence: number; matchedText: string };
  host?: { name: string; confidence: number; matchedText: string };
  userinterface?: { name: string; confidence: number; matchedText: string };
  testcase?: { id: string; confidence: number; matchedText: string };
  campaign?: { id: string; confidence: number; matchedText: string };
}

export interface AvailableEntities {
  devices: Array<{ device_id: string; device_name: string; host_name: string }>;
  hosts: Array<{ host_name: string; host_id?: string }>;
  userinterfaces: Array<{ name: string; id?: string }>;
  testcases: Array<{ testcase_id: string; testcase_name: string }>;
  campaigns: Array<{ campaign_id: string; campaign_name: string }>;
}

/**
 * Calculate similarity between two strings using Levenshtein distance
 */
function calculateSimilarity(str1: string, str2: string): number {
  const longer = str1.length > str2.length ? str1 : str2;
  const shorter = str1.length > str2.length ? str2 : str1;

  if (longer.length === 0) return 1.0;

  const distance = levenshteinDistance(longer, shorter);
  return (longer.length - distance) / longer.length;
}

/**
 * Levenshtein distance calculation
 */
function levenshteinDistance(str1: string, str2: string): number {
  const matrix = [];

  for (let i = 0; i <= str2.length; i++) {
    matrix[i] = [i];
  }

  for (let j = 0; j <= str1.length; j++) {
    matrix[0][j] = j;
  }

  for (let i = 1; i <= str2.length; i++) {
    for (let j = 1; j <= str1.length; j++) {
      if (str2.charAt(i - 1) === str1.charAt(j - 1)) {
        matrix[i][j] = matrix[i - 1][j - 1];
      } else {
        matrix[i][j] = Math.min(
          matrix[i - 1][j - 1] + 1,
          matrix[i][j - 1] + 1,
          matrix[i - 1][j] + 1
        );
      }
    }
  }

  return matrix[str2.length][str1.length];
}

/**
 * Find best match for a text fragment against a list of entities
 */
function findBestMatch(
  text: string,
  entities: Array<{ id: string; name: string; searchTerms?: string[] }>,
  minConfidence: number = 0.7
): { entity: any; confidence: number; matchedText: string } | null {
  let bestMatch = null;
  let bestConfidence = 0;

  // Split text into words and phrases for matching
  const words = text.toLowerCase().split(/\s+/);
  const phrases = [];

  // Generate 1-3 word phrases
  for (let i = 0; i < words.length; i++) {
    for (let j = 1; j <= Math.min(3, words.length - i); j++) {
      phrases.push(words.slice(i, i + j).join(' '));
    }
  }

  for (const entity of entities) {
    const searchTargets = [
      entity.name.toLowerCase(),
      ...(entity.searchTerms || [])
    ];

    for (const target of searchTargets) {
      for (const phrase of phrases) {
        const similarity = calculateSimilarity(phrase, target);

        // Boost confidence for exact matches
        const adjustedConfidence = phrase === target ? similarity * 1.2 :
                                 similarity > 0.9 ? similarity * 1.1 : similarity;

        if (adjustedConfidence > bestConfidence && adjustedConfidence >= minConfidence) {
          bestMatch = entity;
          bestConfidence = adjustedConfidence;
        }
      }
    }
  }

  return bestMatch && bestConfidence >= minConfidence
    ? { entity: bestMatch, confidence: bestConfidence, matchedText: text }
    : null;
}

/**
 * Analyze text for entity mentions
 */
export function analyzeTextForEntities(
  text: string,
  availableEntities: AvailableEntities
): DetectedEntities {
  const result: DetectedEntities = {};

  // Clean and prepare text
  const cleanText = text.toLowerCase().trim();

  if (!cleanText) return result;

  // Device detection
  const deviceMatch = findBestMatch(cleanText, availableEntities.devices.map(d => ({
    id: d.device_id,
    name: d.device_name,
    searchTerms: [d.device_name.toLowerCase(), d.device_id.toLowerCase()]
  })));

  if (deviceMatch) {
    result.device = {
      id: deviceMatch.entity.id,
      confidence: deviceMatch.confidence,
      matchedText: deviceMatch.matchedText
    };
  }

  // Host detection
  const hostMatch = findBestMatch(cleanText, availableEntities.hosts.map(h => ({
    id: h.host_name,
    name: h.host_name,
    searchTerms: [h.host_name.toLowerCase(), h.host_id?.toLowerCase()].filter((term): term is string => Boolean(term))
  })));

  if (hostMatch) {
    result.host = {
      name: hostMatch.entity.id,
      confidence: hostMatch.confidence,
      matchedText: hostMatch.matchedText
    };
  }

  // UserInterface detection
  const uiMatch = findBestMatch(cleanText, availableEntities.userinterfaces.map(ui => ({
    id: ui.name,
    name: ui.name,
    searchTerms: [ui.name.toLowerCase(), ui.id?.toLowerCase()].filter((term): term is string => Boolean(term))
  })));

  if (uiMatch) {
    result.userinterface = {
      name: uiMatch.entity.id,
      confidence: uiMatch.confidence,
      matchedText: uiMatch.matchedText
    };
  }

  // TestCase detection
  const testcaseMatch = findBestMatch(cleanText, availableEntities.testcases.map(tc => ({
    id: tc.testcase_id,
    name: tc.testcase_name,
    searchTerms: [
      tc.testcase_name.toLowerCase(),
      tc.testcase_id.toLowerCase(),
      // Add common variations
      tc.testcase_name.toLowerCase().replace(/\s+/g, '-'),
      tc.testcase_name.toLowerCase().replace(/\s+/g, '_')
    ]
  })));

  if (testcaseMatch) {
    result.testcase = {
      id: testcaseMatch.entity.id,
      confidence: testcaseMatch.confidence,
      matchedText: testcaseMatch.matchedText
    };
  }

  // Campaign detection
  const campaignMatch = findBestMatch(cleanText, availableEntities.campaigns.map(c => ({
    id: c.campaign_id,
    name: c.campaign_name,
    searchTerms: [
      c.campaign_name.toLowerCase(),
      c.campaign_id.toLowerCase(),
      // Add common variations
      c.campaign_name.toLowerCase().replace(/\s+/g, '-'),
      c.campaign_name.toLowerCase().replace(/\s+/g, '_')
    ]
  })));

  if (campaignMatch) {
    result.campaign = {
      id: campaignMatch.entity.id,
      confidence: campaignMatch.confidence,
      matchedText: campaignMatch.matchedText
    };
  }

  return result;
}

/**
 * Get recommended UI actions based on detected entities
 */
export function getRecommendedUIActions(
  detectedEntities: DetectedEntities,
  currentSelections: {
    device?: string;
    userinterface?: string;
    testcase?: string;
    campaign?: string;
  }
) {
  const actions = {
    showContentViewer: false,
    activeTab: 'device-preview' as 'device-preview' | 'navigation' | 'testcase' | 'campaign' | 'heatmap' | 'alerts',
    updateSelections: {} as Partial<typeof currentSelections>,
    confidence: 0
  };

  // Calculate overall confidence
  const confidences = Object.values(detectedEntities)
    .map(e => e?.confidence || 0)
    .filter(c => c > 0);

  if (confidences.length === 0) return actions;

  actions.confidence = Math.max(...confidences);

  // Only proceed if we have reasonable confidence
  if (actions.confidence < 0.6) return actions;

  // Determine what to show and which tab to activate
  if (detectedEntities.device || detectedEntities.host) {
    actions.showContentViewer = true;
    actions.activeTab = 'device-preview';

    if (detectedEntities.device && detectedEntities.device.id !== currentSelections.device) {
      actions.updateSelections.device = detectedEntities.device.id;
    }
  }

  if (detectedEntities.userinterface) {
    actions.showContentViewer = true;
    actions.activeTab = 'navigation';

    if (detectedEntities.userinterface.name !== currentSelections.userinterface) {
      actions.updateSelections.userinterface = detectedEntities.userinterface.name;
    }
  }

  if (detectedEntities.testcase) {
    actions.showContentViewer = true;
    actions.activeTab = 'testcase';

    if (detectedEntities.testcase.id !== currentSelections.testcase) {
      actions.updateSelections.testcase = detectedEntities.testcase.id;
    }
  }

  if (detectedEntities.campaign) {
    actions.showContentViewer = true;
    actions.activeTab = 'campaign';

    if (detectedEntities.campaign.id !== currentSelections.campaign) {
      actions.updateSelections.campaign = detectedEntities.campaign.id;
    }
  }

  return actions;
}
