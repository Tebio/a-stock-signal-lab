CREATE TABLE event_freeze_policies (
    policy_id TEXT PRIMARY KEY,
    policy_version TEXT NOT NULL,
    event_type TEXT NOT NULL,
    freeze_scope TEXT NOT NULL CHECK (
        freeze_scope IN ('all_scoring','new_entry','add','tactical_t','risk_review')
    ),
    minimum_severity TEXT NOT NULL CHECK (
        minimum_severity IN ('info','watch','high','critical')
    ),
    accepted_evidence_tiers_json TEXT NOT NULL,
    release_condition TEXT NOT NULL,
    active INTEGER NOT NULL CHECK (active IN (0,1)),
    created_at_ms INTEGER NOT NULL,
    UNIQUE (policy_version, event_type, freeze_scope)
);

CREATE TABLE override_requests (
    request_id TEXT PRIMARY KEY,
    freeze_id TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    requested_action TEXT NOT NULL CHECK (
        requested_action IN ('release','allow_new_entry','allow_add','allow_tactical_t')
    ),
    request_reason TEXT NOT NULL,
    request_evidence_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('pending','approved','rejected','withdrawn')
    ),
    reviewed_by TEXT,
    review_note TEXT,
    reviewed_at_ms INTEGER,
    created_at_ms INTEGER NOT NULL,
    CHECK (
        (status='pending' AND reviewed_at_ms IS NULL) OR
        (status<>'pending' AND reviewed_at_ms IS NOT NULL)
    ),
    FOREIGN KEY (freeze_id) REFERENCES event_freezes(freeze_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE UNIQUE INDEX idx_event_freezes_one_active_policy_scope
ON event_freezes(code, event_version_id, freeze_scope, policy_version)
WHERE status='active';

CREATE INDEX idx_override_requests_freeze_status
ON override_requests(freeze_id, status, created_at_ms);

INSERT INTO event_freeze_policies VALUES
('default-v1-suspension-all','default-freeze-v1','TRADING_SUSPENSION','all_scoring','info','["A","B"]','official resumption event and risk review',1,0),
('default-v1-resumption-entry','default-freeze-v1','TRADING_RESUMPTION','new_entry','info','["A","B"]','post-resumption review completed',1,0),
('default-v1-resumption-add','default-freeze-v1','TRADING_RESUMPTION','add','info','["A","B"]','post-resumption review completed',1,0),
('default-v1-inquiry-entry','default-freeze-v1','REGULATORY_INQUIRY','new_entry','watch','["A","B"]','official response reviewed',1,0),
('default-v1-inquiry-add','default-freeze-v1','REGULATORY_INQUIRY','add','watch','["A","B"]','official response reviewed',1,0),
('default-v1-discipline-all','default-freeze-v1','DISCIPLINARY_ACTION','all_scoring','watch','["A","B"]','disciplinary impact reviewed',1,0),
('default-v1-major-entry','default-freeze-v1','MAJOR_ANNOUNCEMENT','new_entry','high','["A","B"]','major announcement classified',1,0),
('default-v1-major-add','default-freeze-v1','MAJOR_ANNOUNCEMENT','add','high','["A","B"]','major announcement classified',1,0),
('default-v1-company-entry','default-freeze-v1','COMPANY_ANNOUNCEMENT','new_entry','high','["A","B"]','major announcement classified',1,0),
('default-v1-reg-discipline-all','default-freeze-v1','REGULATORY_DISCIPLINE','all_scoring','watch','["A","B"]','disciplinary impact reviewed',1,0);
