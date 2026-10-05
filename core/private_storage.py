from django.core.files.base import ContentFile
from django.core.files.storage import Storage


class DatabasePrivateStorage(Storage):
    """Server-only storage for small identity documents on ephemeral hosts."""

    def _model(self):
        from .models import PrivateDocument
        return PrivateDocument

    def _save(self, name, content):
        data = content.read()
        self._model().objects.create(path=name, content=data, size=len(data))
        return name

    def _open(self, name, mode="rb"):
        record = self._model().objects.get(path=name)
        return ContentFile(bytes(record.content), name=name)

    def exists(self, name):
        return self._model().objects.filter(path=name).exists()

    def size(self, name):
        return self._model().objects.only("size").get(path=name).size

    def delete(self, name):
        if name:
            self._model().objects.filter(path=name).delete()

    def url(self, name):
        raise ValueError("Private identity documents do not have public URLs.")
