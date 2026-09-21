# Import all models so they register with Base before init_db() calls create_all()
from laptop.models.portfolio import Project  # noqa: F401
from laptop.models.events import Event       # noqa: F401
