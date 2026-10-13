"""
AI-dataset feature - backend_server part (docs/technical/FEATURES.md).

Registered by shared/src/lib/utils/features.py when the feature is enabled:
  /server/training-samples/*   review of AI training samples + eval freeze (TASK-27 step 4),
                               admin-only (ai.training:view / ai.training:review)
Capture itself (shared/src/lib/ai/training_samples.py, the DB module, the hooks) is core
and inert unless TRAINING_DATA_ENABLED is set; this part only reads and labels rows.
"""
from .server_training_samples_routes import server_training_samples_bp


def register(app):
    app.register_blueprint(server_training_samples_bp)
