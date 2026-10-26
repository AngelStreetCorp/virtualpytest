"""Analyzer registry. A profile names analyzers by `type` in its manifest (monitor/profiles.py)."""
from monitor.analyzers.tv_app import TvAppAnalyzer

REGISTRY = {'tv_app': TvAppAnalyzer}   # analyzers that are a profile by themselves; the rest are pipeline stages (pipeline.py)


def build_analyzers(core, profile):
    """The analyzers one profile's img service runs: tv_app has its own; everything else is a pipeline
    (detector, attributors, tracker, events, KPIs)."""
    types = [a.type for a in profile.img.analyzers]
    if types == ['tv_app']:
        return [TvAppAnalyzer(core)]
    if types == ['ad_meter']:
        from monitor.analyzers.ad_meter import AdMeterAnalyzer
        return [AdMeterAnalyzer(core, profile)]
    if types == ['telemetry']:
        from monitor.analyzers.telemetry import TelemetryAnalyzer
        return [TelemetryAnalyzer(core, profile)]
    from monitor.analyzers.pipeline import PipelineAnalyzer
    return [PipelineAnalyzer(core, profile)]
