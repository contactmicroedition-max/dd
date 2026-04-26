import requests
import phonenumbers
from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm, PasswordChangeForm, SetPasswordForm, PasswordResetForm, _unicode_ci_compare
from django.conf import settings
from phonenumbers.phonenumberutil import NumberParseException
from .models import CustomUser, StreamRecording


def verify_recaptcha(token):
    """Verify reCAPTCHA token with Google API."""
    data = {
        'secret': settings.RECAPTCHA_PRIVATE_KEY,
        'response': token,
    }
    try:
        r = requests.post('https://www.google.com/recaptcha/api/siteverify', data=data, timeout=5)
        result = r.json()
        return result.get('success', False)
    except Exception:
        return False


class LoginForm(AuthenticationForm):
    username = forms.CharField(
        widget=forms.TextInput(attrs={'placeholder': 'Username or Email', 'class': 'form-input', 'autofocus': True})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': 'Password', 'class': 'form-input'})
    )
    remember_me = forms.BooleanField(required=False)
    recaptcha_token = forms.CharField(widget=forms.HiddenInput(), required=False)

    def __init__(self, *args, **kwargs):
        self.language = kwargs.pop('language', 'en')
        super().__init__(*args, **kwargs)

        placeholders = {
            'en': ('Username or Email', 'Password'),
            'ar': ('اسم المستخدم او البريد', 'كلمة المرور'),
            'fr': ("Nom d'utilisateur ou e-mail", 'Mot de passe'),
        }
        username_ph, password_ph = placeholders.get(self.language, placeholders['en'])
        self.fields['username'].widget.attrs['placeholder'] = username_ph
        self.fields['password'].widget.attrs['placeholder'] = password_ph

    def clean(self):
        cleaned = super().clean()
        token = (cleaned.get('recaptcha_token') or '').strip()
        if not token:
            msg = {
                'ar': 'يرجى اكمال reCAPTCHA.',
                'fr': 'Veuillez completer le reCAPTCHA.',
                'en': 'Please complete reCAPTCHA.',
            }.get(self.language, 'Please complete reCAPTCHA.')
            raise forms.ValidationError(msg)

        if not verify_recaptcha(token):
            msg = {
                'ar': 'فشل التحقق من reCAPTCHA. حاول مرة اخرى.',
                'fr': 'La verification reCAPTCHA a echoue. Veuillez reessayer.',
                'en': 'reCAPTCHA verification failed. Please try again.',
            }.get(self.language, 'reCAPTCHA verification failed. Please try again.')
            raise forms.ValidationError(msg)
        return cleaned


class RegisterForm(UserCreationForm):
    PHONE_COUNTRY_CHOICES = [
        ('TN', 'Tunisia (+216)'),
        ('DZ', 'Algeria (+213)'),
        ('MA', 'Morocco (+212)'),
        ('EG', 'Egypt (+20)'),
        ('SA', 'Saudi Arabia (+966)'),
        ('AE', 'UAE (+971)'),
        ('QA', 'Qatar (+974)'),
        ('KW', 'Kuwait (+965)'),
        ('OM', 'Oman (+968)'),
        ('BH', 'Bahrain (+973)'),
        ('JO', 'Jordan (+962)'),
        ('LB', 'Lebanon (+961)'),
        ('TR', 'Turkey (+90)'),
        ('FR', 'France (+33)'),
        ('DE', 'Germany (+49)'),
        ('IT', 'Italy (+39)'),
        ('ES', 'Spain (+34)'),
        ('GB', 'United Kingdom (+44)'),
        ('US', 'United States (+1)'),
        ('CA', 'Canada (+1)'),
    ]

    first_name = forms.CharField(
        max_length=50,
        widget=forms.TextInput(attrs={'placeholder': 'First Name', 'class': 'form-input'})
    )
    last_name = forms.CharField(
        max_length=50,
        widget=forms.TextInput(attrs={'placeholder': 'Last Name', 'class': 'form-input'})
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={'placeholder': 'Email Address', 'class': 'form-input'})
    )
    department = forms.CharField(
        max_length=100, required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Department (optional)', 'class': 'form-input'})
    )
    phone_country = forms.ChoiceField(
        choices=PHONE_COUNTRY_CHOICES,
        initial='TN',
        widget=forms.Select(attrs={'class': 'form-input form-select'})
    )
    phone = forms.CharField(
        max_length=32, required=True,
        widget=forms.TextInput(attrs={'placeholder': 'Phone Number', 'class': 'form-input'})
    )
    recaptcha_token = forms.CharField(widget=forms.HiddenInput(), required=False)
    terms = forms.BooleanField(required=True, error_messages={'required': 'You must accept the terms.'})

    class Meta:
        model = CustomUser
        fields = ['username', 'first_name', 'last_name', 'email', 'department', 'phone_country', 'phone', 'password1', 'password2']

    def __init__(self, *args, **kwargs):
        self.language = kwargs.pop('language', 'en')
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if not isinstance(field.widget, forms.HiddenInput):
                field.widget.attrs.setdefault('class', 'form-input')

        placeholders = {
            'en': {
                'username': 'Username',
                'password1': 'Password',
                'password2': 'Confirm Password',
                'first_name': 'First Name',
                'last_name': 'Last Name',
                'email': 'Email Address',
                'department': 'Department (optional)',
                'phone': 'Phone Number',
            },
            'ar': {
                'username': 'اسم المستخدم',
                'password1': 'كلمة المرور',
                'password2': 'تأكيد كلمة المرور',
                'first_name': 'الاسم',
                'last_name': 'اللقب',
                'email': 'البريد الالكتروني',
                'department': 'القسم (اختياري)',
                'phone': 'رقم الهاتف',
            },
            'fr': {
                'username': "Nom d'utilisateur",
                'password1': 'Mot de passe',
                'password2': 'Confirmer le mot de passe',
                'first_name': 'Prenom',
                'last_name': 'Nom',
                'email': 'Adresse e-mail',
                'department': 'Departement (facultatif)',
                'phone': 'Numero de telephone',
            },
        }
        p = placeholders.get(self.language, placeholders['en'])
        for field_name in ['username', 'password1', 'password2', 'first_name', 'last_name', 'email', 'department', 'phone']:
            if field_name in self.fields:
                self.fields[field_name].widget.attrs['placeholder'] = p[field_name]

        country_labels = {
            'en': 'Country',
            'ar': 'الدولة',
            'fr': 'Pays',
        }
        self.fields['phone_country'].label = country_labels.get(self.language, 'Country')

        self.fields['terms'].error_messages = {
            'required': {
                'ar': 'يجب الموافقة على الشروط.',
                'fr': 'Vous devez accepter les conditions.',
                'en': 'You must accept the terms.',
            }.get(self.language, 'You must accept the terms.')
        }

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if CustomUser.objects.filter(email=email).exists():
            msg = {
                'ar': 'يوجد حساب بهذا البريد الالكتروني بالفعل.',
                'fr': 'Un compte avec cet e-mail existe deja.',
                'en': 'An account with this email already exists.',
            }.get(self.language, 'An account with this email already exists.')
            raise forms.ValidationError(msg)
        return email

    def clean_phone(self):
        raw_phone = (self.cleaned_data.get('phone') or '').strip()
        region = (self.cleaned_data.get('phone_country') or '').strip().upper()

        if not raw_phone:
            msg = {
                'ar': 'رقم الهاتف مطلوب.',
                'fr': 'Le numero de telephone est obligatoire.',
                'en': 'Phone number is required.',
            }.get(self.language, 'Phone number is required.')
            raise forms.ValidationError(msg)

        try:
            parsed = phonenumbers.parse(raw_phone, region or None)
        except NumberParseException:
            msg = {
                'ar': 'يرجى ادخال رقم هاتف صالح للدولة المحددة.',
                'fr': 'Veuillez saisir un numero valide pour le pays selectionne.',
                'en': 'Please enter a valid phone number for the selected country.',
            }.get(self.language, 'Please enter a valid phone number for the selected country.')
            raise forms.ValidationError(msg)

        if not phonenumbers.is_possible_number(parsed) or not phonenumbers.is_valid_number(parsed):
            msg = {
                'ar': 'يرجى ادخال رقم هاتف صالح للدولة المحددة.',
                'fr': 'Veuillez saisir un numero valide pour le pays selectionne.',
                'en': 'Please enter a valid phone number for the selected country.',
            }.get(self.language, 'Please enter a valid phone number for the selected country.')
            raise forms.ValidationError(msg)

        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)

    def clean(self):
        cleaned = super().clean()
        token = (cleaned.get('recaptcha_token') or '').strip()
        if not token:
            msg = {
                'ar': 'يرجى اكمال reCAPTCHA.',
                'fr': 'Veuillez completer le reCAPTCHA.',
                'en': 'Please complete reCAPTCHA.',
            }.get(self.language, 'Please complete reCAPTCHA.')
            raise forms.ValidationError(msg)

        if not verify_recaptcha(token):
            msg = {
                'ar': 'فشل التحقق من reCAPTCHA.',
                'fr': 'La verification reCAPTCHA a echoue.',
                'en': 'reCAPTCHA verification failed.',
            }.get(self.language, 'reCAPTCHA verification failed.')
            raise forms.ValidationError(msg)
        return cleaned


class ProfileUpdateForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        lang = 'en'
        if self.instance and getattr(self.instance, 'language', None):
            lang = self.instance.language

        theme_labels = {
            'en': {
                'dark': 'Dark Modern',
                'light': 'Light Professional',
                'vibrant': 'Vibrant Neon',
                'sage': 'Sage Calm',
                'sand': 'Sandstone Soft',
            },
            'ar': {
                'dark': 'داكن حديث',
                'light': 'فاتح احترافي',
                'vibrant': 'حيوي نيون',
                'sage': 'مريمي هادئ',
                'sand': 'رملي ناعم',
            },
            'fr': {
                'dark': 'Sombre moderne',
                'light': 'Clair professionnel',
                'vibrant': 'Neon vibrant',
                'sage': 'Sauge douce',
                'sand': 'Sable doux',
            },
        }

        language_labels = {
            'en': {'en': 'English', 'ar': 'Arabic', 'fr': 'French'},
            'ar': {'en': 'الانجليزية', 'ar': 'العربية', 'fr': 'الفرنسية'},
            'fr': {'en': 'Anglais', 'ar': 'Arabe', 'fr': 'Francais'},
        }

        t_theme = theme_labels.get(lang, theme_labels['en'])
        t_lang = language_labels.get(lang, language_labels['en'])

        self.fields['theme'].choices = [
            (value, t_theme.get(value, label))
            for value, label in self.fields['theme'].choices
        ]
        self.fields['language'].choices = [
            (value, t_lang.get(value, label))
            for value, label in self.fields['language'].choices
        ]

    class Meta:
        model = CustomUser
        fields = ['username', 'first_name', 'last_name', 'email', 'phone', 'department', 'avatar', 'theme', 'language']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-input'}),
            'first_name': forms.TextInput(attrs={'class': 'form-input'}),
            'last_name': forms.TextInput(attrs={'class': 'form-input'}),
            'email': forms.EmailInput(attrs={'class': 'form-input'}),
            'phone': forms.TextInput(attrs={'class': 'form-input'}),
            'department': forms.TextInput(attrs={'class': 'form-input'}),
            'avatar': forms.FileInput(attrs={'class': 'form-input', 'accept': 'image/*'}),
            'theme': forms.Select(attrs={'class': 'form-input form-select'}),
            'language': forms.Select(attrs={'class': 'form-input form-select'}),
        }

    def clean_avatar(self):
        avatar = self.cleaned_data.get('avatar')
        if avatar and hasattr(avatar, 'content_type'):
            # Only validate newly uploaded files (they have content_type)
            # Existing files don't have this attribute
            # Check file size (max 5MB)
            if avatar.size > 5 * 1024 * 1024:
                raise forms.ValidationError("Avatar file size must be less than 5MB.")
            # Check file type
            allowed_types = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
            if avatar.content_type not in allowed_types:
                raise forms.ValidationError("Avatar must be a valid image file (JPG, PNG, GIF, or WebP).")
        return avatar


class CustomPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-input'


class CustomSetPasswordForm(SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-input'


class CustomPasswordResetForm(PasswordResetForm):
    """Allow reset emails for users created via Google OAuth who have no local password yet."""

    def get_users(self, email):
        email_field_name = CustomUser.get_email_field_name()
        active_users = CustomUser._default_manager.filter(
            **{
                f'{email_field_name}__iexact': email,
                'is_active': True,
            }
        )
        return (
            user for user in active_users
            if (user.has_usable_password() or user.google_id)
            and _unicode_ci_compare(email, getattr(user, email_field_name))
        )


class StreamRecordingUploadForm(forms.ModelForm):
    class Meta:
        model = StreamRecording
        fields = ['title', 'drone', 'recording_file', 'duration_seconds', 'description']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Recording title'}),
            'drone': forms.Select(attrs={'class': 'form-input form-select'}),
            'recording_file': forms.FileInput(attrs={'class': 'form-input', 'accept': 'video/*'}),
            'duration_seconds': forms.NumberInput(attrs={'class': 'form-input', 'min': 1}),
            'description': forms.Textarea(attrs={'class': 'form-input', 'rows': 3, 'placeholder': 'Optional notes'}),
        }

    def clean_recording_file(self):
        recording_file = self.cleaned_data.get('recording_file')
        if not recording_file:
            raise forms.ValidationError('Recording file is required.')

        allowed_ext = ('.mp4', '.webm', '.mov', '.mkv', '.avi')
        filename = (recording_file.name or '').lower()
        if not filename.endswith(allowed_ext):
            raise forms.ValidationError('Unsupported recording format. Use MP4, WEBM, MOV, MKV, or AVI.')

        max_size = 1024 * 1024 * 1024  # 1GB
        if getattr(recording_file, 'size', 0) > max_size:
            raise forms.ValidationError('Recording file must be smaller than 1GB.')

        return recording_file
