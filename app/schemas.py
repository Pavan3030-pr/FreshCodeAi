from typing import List, Optional

from pydantic import BaseModel, Field

LANG_PATTERN = r"^[A-Za-z0-9+#.\- ]{1,40}$"


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)
    display_name: str = Field(default="", max_length=80)


class LoginRequest(BaseModel):
    email: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=200)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


class ProfileUpdate(BaseModel):
    display_name: str = Field(max_length=80)


class DeleteAccount(BaseModel):
    password: str = Field(min_length=1, max_length=200)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)
    language: str = Field(default="python", pattern=LANG_PATTERN)
    constraints: str = Field(default="", max_length=2000)
    context_budget: int = Field(default=900, ge=200, le=4000)


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    description: Optional[str] = Field(default=None, max_length=500)
    language: Optional[str] = Field(default=None, pattern=LANG_PATTERN)
    constraints: Optional[str] = Field(default=None, max_length=2000)
    context_budget: Optional[int] = Field(default=None, ge=200, le=4000)
    archived: Optional[bool] = None


class VerifyRequest(BaseModel):
    text: str = Field(min_length=8, max_length=12000)
    project_id: Optional[int] = None


class CodeRequest(BaseModel):
    task: str = Field(min_length=8, max_length=6000)
    language: str = Field(default="python", pattern=LANG_PATTERN)
    constraints: Optional[str] = Field(default="", max_length=2000)
    verify_facts: bool = True
    auto_test: bool = True       # run the generated test suite (Python and JavaScript)
    auto_repair: bool = True     # one compact repair pass if tests fail
    context_budget: int = Field(default=900, ge=200, le=4000)
    project_id: Optional[int] = None


class BenchmarkRequest(BaseModel):
    task: str = Field(min_length=8, max_length=4000)
    extra_tasks: List[str] = Field(default_factory=list, max_length=4)
    language: str = Field(default="python", pattern=LANG_PATTERN)
    project_id: Optional[int] = None


class TestRequest(BaseModel):
    language: str = Field(default="python", pattern=r"^(python|javascript)$")
    code: str = Field(min_length=1, max_length=20000)
    tests: str = Field(min_length=1, max_length=12000)
    project_id: Optional[int] = None
