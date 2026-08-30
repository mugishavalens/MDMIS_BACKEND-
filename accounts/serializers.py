from django.utils.text import slugify
from rest_framework import serializers

from .models import Organisation, User


class UserPublicSerializer(serializers.ModelSerializer):
    """Shape matches the frontend's `RoleUser` type (frontend/lib/rbac.ts)
    so the login/me responses can be dropped straight into auth-context."""

    name = serializers.CharField(source='full_name')
    roleLabel = serializers.CharField(source='get_role_display', read_only=True)
    initials = serializers.CharField(read_only=True)
    orgId = serializers.SerializerMethodField()
    orgName = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['name', 'email', 'role', 'roleLabel', 'initials', 'orgId', 'orgName']

    def get_orgId(self, obj):
        return str(obj.organisation_id) if obj.organisation_id else None

    def get_orgName(self, obj):
        return obj.organisation.name if obj.organisation else None


class RegisterSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=255)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    role = serializers.ChoiceField(choices=User.ROLE_CHOICES)
    organisation_name = serializers.CharField(max_length=255, required=False, allow_blank=True)

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError('An account with this email already exists.')
        return value

    def create(self, validated_data):
        org_name = validated_data.pop('organisation_name', '') or f"{validated_data['full_name']}'s Organisation"
        password = validated_data.pop('password')

        slug_base = slugify(org_name) or 'org'
        slug = slug_base
        suffix = 1
        while Organisation.objects.filter(slug=slug).exists():
            suffix += 1
            slug = f'{slug_base}-{suffix}'

        org = Organisation.objects.create(
            name=org_name, slug=slug, primary_contact_email=validated_data['email'],
        )
        user = User(organisation=org, is_active=False, **validated_data)
        user.set_password(password)
        user.save()
        return user


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        # Deliberately not using django.contrib.auth.authenticate(): its
        # ModelBackend rejects inactive users before returning, which would
        # collapse the "pending approval" case into the generic invalid-
        # credentials message. Checking the password directly here lets us
        # tell the two cases apart (matches the register page's copy).
        try:
            user = User.objects.get(email__iexact=attrs['email'])
        except User.DoesNotExist:
            raise serializers.ValidationError('Invalid email or password.')
        if not user.check_password(attrs['password']):
            raise serializers.ValidationError('Invalid email or password.')
        if not user.is_active:
            raise serializers.ValidationError(
                'Your account is pending administrator approval.'
            )
        attrs['user'] = user
        return attrs
