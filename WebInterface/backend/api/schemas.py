"""Request bodies accepted by the HTTP API."""

from typing import Optional

from pydantic import BaseModel, Field


class AddCameraRequest(BaseModel):
    ip: str = Field(..., description="IPv4 address of the camera")
    port: int = Field(80, description="ONVIF port")
    username: Optional[str] = ""
    password: Optional[str] = ""
    name: Optional[str] = Field("", description="Display name; the device name is used when empty")
    rtsp_port: int = Field(554, description="RTSP port")


class UpdateCameraRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = Field(None, description="What the camera sees; context for incident summaries")


class CreateRuleRequest(BaseModel):
    title: str
    scope: str = Field("camera", description="'camera' for one camera, 'system' for every camera")
    camera_id: Optional[str] = None
    camera_name: Optional[str] = None
    severity: str = "warning"
    description: str = ""
    zones: Optional[list] = Field(default_factory=list, description="[{id, name, description, zone_type, points}]")
    actions: Optional[list] = Field(default_factory=list)


class UpdateRuleRequest(BaseModel):
    """Every field is optional: only the given ones are changed."""

    title: Optional[str] = None
    enabled: Optional[bool] = None
    scope: Optional[str] = None
    camera_id: Optional[str] = None
    camera_name: Optional[str] = None
    severity: Optional[str] = None
    description: Optional[str] = None
    zones: Optional[list] = None
    actions: Optional[list] = None


class SimulateAnomalyRequest(BaseModel):
    camera_id: str
    score: float = Field(..., ge=0.0, le=100.0, description="Anomaly score in percent")


class OperatorLabelRequest(BaseModel):
    label: str = Field(..., description="'correct', 'false_positive' or 'unlabeled'")
    notes: Optional[str] = ""
    operator_name: Optional[str] = "Operatör"
