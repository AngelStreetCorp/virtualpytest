"""
AI Intent Parser

Extracts user intent from natural language prompts:
- Keywords extraction (navigation targets, actions, verifications)
- Pattern detection (loops, sequences, conditionals)
- Structure hints for AI graph generation

Handles complex prompts like:
- "Go to live then zap 2 times, for each zap check audio and video"
- "Navigate to home, press OK 3 times, verify screen shows menu"
"""

import re
from typing import Dict, List, Optional, Set


# Common stop words to filter out
STOP_WORDS = {
    'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from', 'has',
    'he', 'in', 'is', 'it', 'its', 'of', 'on', 'that', 'the', 'to', 'was',
    'will', 'with', 'then', 'each', 'times'
}


class IntentParser:
    """
    Parse user prompts to extract intent and structure
    """
    
    # Regex patterns for intent detection
    NAVIGATION_PATTERNS = [
        r'(?:go|navigate|move|switch)\s+to\s+([^,\.\n]+?)(?:\s+then|\s+and|\s*,|\s*\.|\s*$)',
        r'open\s+([^,\.\n]+?)(?:\s+then|\s+and|\s*,|\s*\.|\s*$)',
        r'access\s+([^,\.\n]+?)(?:\s+then|\s+and|\s*,|\s*\.|\s*$)',
    ]
    
    ACTION_PATTERNS = [
        r'(?:press|click|tap|select|push)\s+([^,\.\n]+?)(?:\s+then|\s+and|\s*,|\s*\.|\s*$)',
        r'(?:zap|swipe|scroll)\s*(?:\s+([^,\.\n]+?))?(?:\s+then|\s+and|\s*,|\s*\.|\s*$)',
        r'execute\s+([^,\.\n]+?)(?:\s+then|\s+and|\s*,|\s*\.|\s*$)',
    ]
    
    VERIFICATION_PATTERNS = [
        r'(?:check|verify|confirm|validate|ensure)\s+([^,\.\n]+?)(?:\s+then|\s+and|\s*,|\s*\.|\s*$)',
        r'(?:is|are)\s+([^,\.\n]+?)\s+(?:playing|visible|present|displayed)(?:\s+then|\s+and|\s*,|\s*\.|\s*$)',
    ]
    
    LOOP_PATTERNS = [
        r'(\d+)\s+times',
        r'repeat\s+(\d+)',
        r'for\s+each',
        r'loop\s+(\d+)?',
    ]
    
    SEQUENCE_PATTERNS = [
        r'then',
        r'after\s+that',
        r'next',
        r'followed\s+by',
    ]
    
    CONDITIONAL_PATTERNS = [
        r'if\s+',
        r'when\s+',
        r'unless\s+',
        r'in\s+case',
    ]
    
    def parse_prompt(self, prompt: str) -> Dict:
        """
        Parse prompt to extract complete intent
        
        Args:
            prompt: User's natural language prompt
        
        Returns:
            {
                'keywords': {
                    'navigation': ['live', 'tv'],
                    'actions': ['zap'],
                    'verifications': ['audio', 'video']
                },
                'patterns': {
                    'has_loop': True,
                    'loop_count': 2,
                    'loop_scope': ['zap', 'audio', 'video'],
                    'has_sequence': True,
                    'has_conditional': False
                },
                'structure_type': 'sequence_with_loop',
                'all_keywords': ['live', 'tv', 'zap', 'audio', 'video']
            }
        """
        prompt_lower = prompt.lower()
        
        # Extract keywords by category
        keywords = {
            'navigation': self._extract_keywords(prompt_lower, self.NAVIGATION_PATTERNS),
            'actions': self._extract_keywords(prompt_lower, self.ACTION_PATTERNS),
            'verifications': self._extract_keywords(prompt_lower, self.VERIFICATION_PATTERNS)
        }
        
        # Detect patterns
        patterns = self._detect_patterns(prompt_lower)
        
        # Determine structure type
        structure_type = self._classify_structure(patterns)
        
        # Collect all unique keywords (for context filtering)
        all_keywords = list(set(
            keywords['navigation'] + 
            keywords['actions'] + 
            keywords['verifications']
        ))
        
        result = {
            'keywords': keywords,
            'patterns': patterns,
            'structure_type': structure_type,
            'all_keywords': all_keywords,
            'original_prompt': prompt
        }
        
        print(f"[@intent_parser] Intent analysis:")
        print(f"[@intent_parser]   Structure: {structure_type}")
        print(f"[@intent_parser]   Navigation: {keywords['navigation']}")
        print(f"[@intent_parser]   Actions: {keywords['actions']}")
        print(f"[@intent_parser]   Verifications: {keywords['verifications']}")
        if patterns['has_loop']:
            print(f"[@intent_parser]   Loop: {patterns.get('loop_count', '?')} iterations")
        
        return result
    
    def _extract_keywords(self, prompt: str, patterns: List[str]) -> List[str]:
        """
        Extract keywords from prompt using regex patterns
        
        Returns list of meaningful keywords (stop words removed)
        """
        keywords = []
        
        for pattern in patterns:
            matches = re.finditer(pattern, prompt, re.IGNORECASE)
            for match in matches:
                # Get captured group (the target/action/verification)
                if match.groups():
                    captured = match.group(1)
                    if captured:
                        # Clean and tokenize
                        tokens = self._tokenize(captured.strip())
                        keywords.extend(tokens)
        
        # Remove duplicates and stop words
        keywords = [k for k in keywords if k and k not in STOP_WORDS]
        return list(set(keywords))
    
    def _tokenize(self, text: str) -> List[str]:
        """
        Tokenize text into meaningful words
        
        Handles:
        - "live TV" → ["live", "tv"]
        - "check_audio" → ["check", "audio", "check_audio"]  ← Keep full phrase!
        - "press-ok" → ["press", "ok"]
        
        IMPORTANT: For underscore-separated names, keep BOTH the full name AND parts
        to support node names like "home_tvguide" (don't break them!)
        """
        tokens = []
        
        # Keep original if it contains underscores (likely a node/action name)
        if '_' in text:
            original = text.lower().strip()
            if original and original not in STOP_WORDS and len(original) > 1:
                tokens.append(original)
        
        # Replace special chars with spaces for tokenization
        text_spaced = re.sub(r'[_\-/]', ' ', text)
        # Split on whitespace
        word_tokens = text_spaced.lower().split()
        # Filter out empty and stop words
        tokens.extend([t for t in word_tokens if t and t not in STOP_WORDS and len(t) > 1])
        
        return tokens
    
    def _detect_patterns(self, prompt: str) -> Dict:
        """
        Detect structural patterns in prompt
        
        Returns pattern metadata
        """
        patterns = {
            'has_loop': False,
            'loop_count': None,
            'loop_scope': [],
            'has_sequence': False,
            'has_conditional': False
        }
        
        # Check for loops
        for pattern in self.LOOP_PATTERNS:
            match = re.search(pattern, prompt, re.IGNORECASE)
            if match:
                patterns['has_loop'] = True
                if match.groups():
                    try:
                        patterns['loop_count'] = int(match.group(1))
                    except (ValueError, IndexError):
                        patterns['loop_count'] = None
                break
        
        # Extract loop scope if "for each" pattern
        if 'for each' in prompt or 'for every' in prompt:
            # Try to find what's being looped
            scope_match = re.search(r'for\s+each\s+(\w+)', prompt)
            if scope_match:
                patterns['loop_scope'] = [scope_match.group(1)]
        
        # Check for sequences
        for pattern in self.SEQUENCE_PATTERNS:
            if re.search(pattern, prompt, re.IGNORECASE):
                patterns['has_sequence'] = True
                break
        
        # Check for conditionals
        for pattern in self.CONDITIONAL_PATTERNS:
            if re.search(pattern, prompt, re.IGNORECASE):
                patterns['has_conditional'] = True
                break
        
        return patterns
    
    def _classify_structure(self, patterns: Dict) -> str:
        """
        Classify overall structure type
        
        Returns: 'simple', 'sequence', 'loop', 'sequence_with_loop', 'conditional'
        """
        if patterns['has_conditional']:
            return 'conditional'
        
        if patterns['has_loop'] and patterns['has_sequence']:
            return 'sequence_with_loop'
        
        if patterns['has_loop']:
            return 'loop'
        
        if patterns['has_sequence']:
            return 'sequence'
        
        return 'simple'


def build_structure_hints_for_ai(intent: Dict) -> str:
    """
    Build human-readable structure hints for AI prompt
    
    Helps AI understand how to structure the graph
    
    Args:
        intent: Output from IntentParser.parse_prompt()
    
    Returns:
        Formatted string with structure guidance
    """
    patterns = intent['patterns']
    hints = []
    
    hints.append(f"DETECTED STRUCTURE: {intent['structure_type']}")
    
    if patterns['has_sequence']:
        hints.append("- Use sequential nodes (connect with success edges)")
    
    if patterns['has_loop']:
        loop_count = patterns.get('loop_count', '?')
        hints.append(f"- Create LOOP block with {loop_count} iterations")
        if patterns.get('loop_scope'):
            hints.append(f"  Loop scope: {', '.join(patterns['loop_scope'])}")
    
    if patterns['has_conditional']:
        hints.append("- Include conditional branching (success/failure edges)")
    
    # Provide workflow hints
    if intent['keywords']['navigation']:
        hints.append(f"- Navigation targets: {', '.join(intent['keywords']['navigation'])}")
    
    if intent['keywords']['actions']:
        hints.append(f"- Actions to execute: {', '.join(intent['keywords']['actions'])}")
    
    if intent['keywords']['verifications']:
        hints.append(f"- Verifications to perform: {', '.join(intent['keywords']['verifications'])}")
    
    return '\n'.join(hints)


# Convenience function
def parse_intent(prompt: str) -> Dict:
    """
    Parse user intent from prompt
    
    Quick access function for common use case
    """
    parser = IntentParser()
    return parser.parse_prompt(prompt)

