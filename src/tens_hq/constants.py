"""Stable configuration for the deterministic ReconRadar demonstration."""

from __future__ import annotations

from datetime import date

APP_VERSION = "1.0.0"
DATA_AS_OF_DATE = date(2026, 6, 30)
DEFAULT_SEED = 20260717
DEFAULT_TARGET = 0.75

SYNTHETIC_BANNER = "SYNTHETIC DEMO DATA — NOT FOR EMPLOYMENT OR COMPLIANCE DECISIONS"

JOB_FAMILIES = {
    "CUSTODIAL": ("Custodial Services", 32.0),
    "FACILITIES": ("Facilities Support", 34.0),
    "FOOD": ("Food Services", 30.0),
    "CONTACT": ("Contact Center", 36.0),
    "ADMIN": ("Administrative Support", 36.0),
    "IT": ("IT Service Desk", 38.0),
}

ORGANIZATION_TYPES = {
    "Vocational Rehabilitation": {
        "weight": 0.13,
        "volume": 0.85,
        "apply": 0.82,
        "interview": 0.66,
        "hire": 0.48,
        "clear": 0.88,
        "docs": 0.91,
        "retain90": 0.86,
        "days_clear": 12,
    },
    "Workforce Board": {
        "weight": 0.12,
        "volume": 1.60,
        "apply": 0.76,
        "interview": 0.58,
        "hire": 0.38,
        "clear": 0.62,
        "docs": 0.67,
        "retain90": 0.70,
        "days_clear": 20,
    },
    "Supported Employment Provider": {
        "weight": 0.16,
        "volume": 0.72,
        "apply": 0.87,
        "interview": 0.72,
        "hire": 0.55,
        "clear": 0.91,
        "docs": 0.92,
        "retain90": 0.92,
        "days_clear": 10,
    },
    "Center for Independent Living": {
        "weight": 0.10,
        "volume": 0.78,
        "apply": 0.79,
        "interview": 0.62,
        "hire": 0.43,
        "clear": 0.76,
        "docs": 0.79,
        "retain90": 0.81,
        "days_clear": 16,
    },
    "School Transition Program": {
        "weight": 0.10,
        "volume": 1.05,
        "apply": 0.74,
        "interview": 0.59,
        "hire": 0.41,
        "clear": 0.80,
        "docs": 0.84,
        "retain90": 0.85,
        "days_clear": 25,
    },
    "Veteran-Serving Organization": {
        "weight": 0.08,
        "volume": 0.60,
        "apply": 0.86,
        "interview": 0.70,
        "hire": 0.52,
        "clear": 0.72,
        "docs": 0.78,
        "retain90": 0.84,
        "days_clear": 14,
    },
    "Community College": {
        "weight": 0.10,
        "volume": 1.10,
        "apply": 0.77,
        "interview": 0.63,
        "hire": 0.44,
        "clear": 0.58,
        "docs": 0.65,
        "retain90": 0.73,
        "days_clear": 23,
    },
    "Community Rehabilitation Provider": {
        "weight": 0.11,
        "volume": 0.92,
        "apply": 0.84,
        "interview": 0.69,
        "hire": 0.50,
        "clear": 0.86,
        "docs": 0.88,
        "retain90": 0.87,
        "days_clear": 13,
    },
    "Local Workforce Nonprofit": {
        "weight": 0.10,
        "volume": 0.70,
        "apply": 0.70,
        "interview": 0.52,
        "hire": 0.34,
        "clear": 0.55,
        "docs": 0.58,
        "retain90": 0.66,
        "days_clear": 27,
    },
}

RELATIONSHIP_STATUSES = [
    "Unknown",
    "Cold",
    "Contacted",
    "Warm",
    "Active Partner",
    "Strategic Partner",
    "Dormant",
    "Do Not Contact",
]

SITE_PROFILES = [
    ("North Harbor Services", "Harbor County", "VA", "Custodial Services", 46, 7, 0.738, -0.0020, 4.5),
    ("Western Ridge Contact Center", "Ridge County", "KY", "Contact Center", 71, 3, 0.792, -0.0005, 1.0),
    ("Capital Administrative Center", "Capital County", "MD", "Administrative Support", 58, 5, 0.767, -0.0010, 1.5),
    ("Pine Valley Food Operations", "Pine County", "NC", "Food Services", 52, 6, 0.721, -0.0015, 5.0),
    ("Gulf Shore Facilities", "Gulf County", "FL", "Facilities Support", 64, 4, 0.781, 0.0008, 1.1),
    ("Lakeside Service Desk", "Lake County", "OH", "IT Service Desk", 39, 4, 0.754, -0.0007, 1.3),
    ("Prairie Custodial Hub", "Prairie County", "TX", "Custodial Services", 83, 8, 0.744, 0.0004, 2.2),
    ("Bluegrass Food Center", "Bluegrass County", "KY", "Food Services", 48, 5, 0.803, -0.0006, 1.0),
    ("Tidewater Support Center", "Tide County", "VA", "Facilities Support", 55, 2, 0.824, 0.0005, 0.7),
    ("Sandhill Administration", "Sandhill County", "NC", "Administrative Support", 44, 6, 0.706, -0.0012, 2.0),
    ("Suncoast Contact Operations", "Sun County", "FL", "Contact Center", 67, 4, 0.769, 0.0002, 1.2),
    ("Buckeye Integrated Services", "Buckeye County", "OH", "Custodial Services", 74, 5, 0.786, 0.0006, 1.0),
]

COUNTY_NAMES = {
    "VA": ["Harbor", "Tide", "Bay", "Cedar", "River", "Commonwealth"],
    "KY": ["Ridge", "Bluegrass", "Bourbon", "Meadow", "Cumberland", "Derby"],
    "MD": ["Capital", "Chesapeake", "Patuxent", "Monument", "Severn", "Laurel"],
    "NC": ["Pine", "Sandhill", "Cape", "Piedmont", "Catawba", "Dogwood"],
    "FL": ["Gulf", "Sun", "Palm", "Orange", "Lagoon", "Cypress"],
    "OH": ["Lake", "Buckeye", "Summit", "Miami Valley", "Scioto", "Erie"],
    "TX": ["Prairie", "Lone Star", "Trinity", "Mesa", "Brazos", "Alamo"],
    "PA": ["Keystone", "Allegheny", "Liberty", "Susquehanna", "Laurel Ridge", "Delaware Valley"],
}

PROHIBITED_COLUMN_TOKENS = {
    "diagnosis",
    "doctor_note",
    "medical_record",
    "accommodation_detail",
    "iep",
    "504_detail",
    "psychological_evaluation",
    "disability_narrative",
}
