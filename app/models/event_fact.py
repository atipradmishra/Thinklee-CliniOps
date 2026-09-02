from app.extensions import db

class EventFact(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    file_metadata_id = db.Column(db.Integer, nullable=False)
    event_text = db.Column(db.Text, nullable=False)
    normalized_event_text = db.Column(db.Text, nullable=False)

    event_date = db.Column(db.Date, nullable=False)
    event_time = db.Column(db.Time, nullable=True)
    event_datetime = db.Column(db.DateTime, index=True)

    contains_overlast = db.Column(db.Boolean, default=False)
