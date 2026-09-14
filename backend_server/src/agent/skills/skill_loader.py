"""
Skill Loader

Loads skill definitions from YAML files and provides access to them.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional
import yaml

from .skill_schema import SkillDefinition

logger = logging.getLogger(__name__)


class SkillLoader:
    """
    Loads and manages skill definitions from YAML files
    
    Skills are loaded once at startup and cached in memory.
    """
    
    # Class-level cache for loaded skills
    _skills: Dict[str, SkillDefinition] = {}
    _loaded: bool = False
    
    @classmethod
    def _parse_skill_md(cls, skill_md_path: Path) -> dict:
        """
        Parse a SKILL.md file (YAML frontmatter + markdown body).
        Returns a dict compatible with SkillDefinition constructor.
        """
        raw = skill_md_path.read_text(encoding='utf-8')

        # Split YAML frontmatter from markdown body
        import re
        fm_match = re.match(r'^---\n(.*?)\n---\n(.*)$', raw, re.DOTALL)
        if not fm_match:
            raise ValueError("SKILL.md must start with --- YAML frontmatter ---")

        frontmatter = yaml.safe_load(fm_match.group(1))
        body = fm_match.group(2).strip()

        # The markdown body becomes the system_prompt
        result = dict(frontmatter)
        result['system_prompt'] = body

        # Extract triggers from body if not in frontmatter
        if 'triggers' not in result:
            result['triggers'] = []

        return result

    @classmethod
    def load_all_skills(cls) -> None:
        """
        Load all skill definitions from SKILL.md files in subdirectories.
        Supports both new format (skill-name/SKILL.md) and legacy YAML (skill-name.yaml).
        Called once on server startup.
        """
        if cls._loaded:
            return

        definitions_dir = Path(__file__).parent / 'definitions'

        if not definitions_dir.exists():
            logger.warning(f"[skills] Definitions directory not found: {definitions_dir}")
            cls._loaded = True
            return

        # Find all skill sources: SKILL.md in subdirs + legacy .yaml files
        skill_sources = []
        for entry in sorted(definitions_dir.iterdir()):
            if entry.is_dir():
                skill_md = entry / 'SKILL.md'
                if skill_md.exists():
                    skill_sources.append(('md', skill_md))
            elif entry.suffix == '.yaml':
                skill_sources.append(('yaml', entry))

        # Optional features contribute skills from features/<name>/skills/<skill>/SKILL.md
        # (docs/technical/FEATURES.md). A disabled feature's folder is not deployed, so
        # its skills simply do not exist here.
        try:
            from shared.src.lib.utils.features import enabled_feature_dirs
            for feat_name, skills_dir in enabled_feature_dirs('skills'):
                for entry in sorted(Path(skills_dir).iterdir()):
                    skill_md = entry / 'SKILL.md'
                    if entry.is_dir() and skill_md.exists():
                        skill_sources.append(('md', skill_md))
                        logger.info(f"[skills] feature {feat_name}: {entry.name}")
        except Exception as e:
            logger.warning(f"[skills] feature skill discovery failed: {e}")

        logger.info(f"[skills] ═══════════════════════════════════════════════")
        logger.info(f"[skills] Loading {len(skill_sources)} skill definitions...")
        logger.info(f"[skills] ═══════════════════════════════════════════════")

        loaded = 0
        errors = []

        for source_type, source_path in skill_sources:
            try:
                if source_type == 'md':
                    skill_data = cls._parse_skill_md(source_path)
                else:
                    with open(source_path, 'r', encoding='utf-8') as f:
                        skill_data = yaml.safe_load(f)

                skill = SkillDefinition(**skill_data)
                cls._skills[skill.name] = skill

                platform_str = skill.platform or 'all'
                device_str = '🔌' if skill.requires_device else '📝'
                fmt = 'md' if source_type == 'md' else 'yaml'
                logger.info(f"[skills]   {device_str} {skill.name:25} ({platform_str:6}) - {len(skill.tools)} tools [{fmt}]")

                loaded += 1

            except Exception as e:
                errors.append(f"  ❌ {source_path.name}: {e}")

        cls._loaded = True

        if errors:
            logger.error(f"[skills] ")
            logger.error(f"[skills] ⚠️ Failed to Load ({len(errors)}):")
            for line in errors:
                logger.error(f"[skills] {line}")

        logger.info(f"[skills] ")
        logger.info(f"[skills] ═══════════════════════════════════════════════")
        logger.info(f"[skills] Total: {loaded}/{len(skill_sources)} skills loaded")
        logger.info(f"[skills] ═══════════════════════════════════════════════")
    
    @classmethod
    def reload(cls) -> None:
        """Reload all skills from YAML (for development)"""
        cls._skills.clear()
        cls._loaded = False
        cls.load_all_skills()
    
    @classmethod
    def get_skill(cls, skill_name: str) -> Optional[SkillDefinition]:
        """Get a skill by name"""
        if not cls._loaded:
            cls.load_all_skills()
        return cls._skills.get(skill_name)
    
    @classmethod
    def get_all_skills(cls) -> Dict[str, SkillDefinition]:
        """Get all loaded skills"""
        if not cls._loaded:
            cls.load_all_skills()
        return cls._skills.copy()
    
    @classmethod
    def get_skills_for_agent(cls, skill_names: List[str]) -> List[SkillDefinition]:
        """Get skill definitions for a list of skill names"""
        if not cls._loaded:
            cls.load_all_skills()
        return [cls._skills[name] for name in skill_names if name in cls._skills]
    
    @classmethod
    def get_skill_descriptions(cls, skill_names: List[str], message: str = "", device_platform: Optional[str] = None) -> str:
        """
        Get formatted descriptions of skills for system prompt

        Args:
            skill_names: List of skill names to include
            message: User message to filter relevant triggers (optional)
            device_platform: Optional device platform to filter skills ('mobile', 'stb', 'web')

        Returns:
            Token-efficient skill descriptions with relevant triggers highlighted
        """
        if not cls._loaded:
            cls.load_all_skills()

        message_lower = message.lower() if message else ""

        # Filter skills by platform if specified
        filtered_skill_names = []
        for name in skill_names:
            skill = cls._skills.get(name)
            if skill and device_platform:
                skill_platform = skill.platform
                if skill_platform == 'all' or skill_platform is None:
                    filtered_skill_names.append(name)  # Skill works on all platforms
                elif device_platform == 'mobile' and skill_platform in ['mobile']:
                    filtered_skill_names.append(name)  # Mobile platform matches
                elif device_platform == 'stb' and skill_platform in ['stb']:
                    filtered_skill_names.append(name)  # STB platform matches
                elif device_platform == 'web' and skill_platform in ['web']:
                    filtered_skill_names.append(name)  # Web platform matches
                # Skip skills that don't match the platform
            elif skill:
                filtered_skill_names.append(name)  # No platform filtering

        lines = []

        for name in filtered_skill_names:
            skill = cls._skills.get(name)
            if skill:
                platform_str = f" [{skill.platform}]" if skill.platform else ""

                # Find matching triggers for this message
                matching_triggers = [t for t in skill.triggers if t.lower() in message_lower]
                other_triggers = [t for t in skill.triggers if t not in matching_triggers]

                # Build trigger string (prioritize matching triggers)
                trigger_parts = []
                if matching_triggers:
                    trigger_parts.extend(f'**{t}**' for t in matching_triggers[:3])  # Highlight matches
                if other_triggers:
                    trigger_parts.extend(other_triggers[:2])  # Show a few others
                if len(skill.triggers) > 5:
                    trigger_parts.append(f"+{len(skill.triggers)-5} more")

                triggers_str = ", ".join(trigger_parts) if trigger_parts else "various commands"

                lines.append(f"- **{skill.name}**{platform_str}: {skill.description.split('.')[0]}.")
                if trigger_parts:
                    lines.append(f"  Triggers: {triggers_str}")

        return '\n'.join(lines) if lines else "No skills available."
    
    @classmethod
    def match_skill(cls, message: str, available_skills: List[str], device_platform: Optional[str] = None) -> Optional[SkillDefinition]:
        """
        Find the best matching skill for a user message

        Args:
            message: User message
            available_skills: List of skill names this agent can use
            device_platform: Optional device platform ('mobile', 'stb', 'web') to filter skills

        Returns:
            Best matching SkillDefinition or None
        """
        if not cls._loaded:
            cls.load_all_skills()

        message_lower = message.lower()

        # Filter skills by platform compatibility if device_platform is provided
        candidate_skills = []
        for skill_name in available_skills:
            skill = cls._skills.get(skill_name)
            if not skill:
                continue

            # If device platform is specified, check compatibility
            if device_platform:
                skill_platform = skill.platform
                if skill_platform == 'all' or skill_platform is None:
                    pass  # Skill works on all platforms
                elif device_platform == 'mobile' and skill_platform not in ['mobile']:
                    continue  # Mobile devices should use mobile skills, not stb/web
                elif device_platform == 'stb' and skill_platform not in ['stb']:
                    continue  # STB devices should use stb skills
                elif device_platform == 'web' and skill_platform not in ['web']:
                    continue  # Web devices should use web skills

            candidate_skills.append(skill)

        # Score each candidate skill
        best_skill = None
        best_score = 0

        for skill in candidate_skills:
            score = 0
            for trigger in skill.triggers:
                if trigger.lower() in message_lower:
                    # Longer triggers are more specific = higher score
                    score += len(trigger)

            if score > best_score:
                best_score = score
                best_skill = skill

        return best_skill
    
    @classmethod
    def is_valid_skill(cls, skill_name: str) -> bool:
        """Check if a skill name exists"""
        if not cls._loaded:
            cls.load_all_skills()
        return skill_name in cls._skills
    
    @classmethod
    def validate_skills(cls, skill_names: List[str]) -> tuple[List[str], List[str]]:
        """
        Validate a list of skill names
        
        Returns:
            (valid_skills, invalid_skills)
        """
        if not cls._loaded:
            cls.load_all_skills()
        
        valid = []
        invalid = []
        for name in skill_names:
            if name in cls._skills:
                valid.append(name)
            else:
                invalid.append(name)
        return valid, invalid

