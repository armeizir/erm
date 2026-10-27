from django import forms
from .models import Document
from .richtext import RICH_FIELDS, clean_value, editor_html


class RichTextWidget(forms.Textarea):
    class Media:
        js = ('smt/editor.js',)
        css = {'all': ('smt/editor.css',)}

    def __init__(self, attrs=None):
        super().__init__({'class': 'smt-rich-editor', 'rows': 10, **(attrs or {})})

    def format_value(self, value):
        # Keep raw text in the textarea fallback. JS uses the sanitized HTML attribute.
        return super().format_value(value)

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context['widget']['attrs']['data-editor-html'] = editor_html(value)
        return context


class DocumentForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = '__all__'
        widgets = {name: RichTextWidget() for name in RICH_FIELDS}

    def clean(self):
        cleaned = super().clean()
        for name in RICH_FIELDS:
            if name in cleaned:
                cleaned[name] = clean_value(cleaned[name])
        return cleaned
