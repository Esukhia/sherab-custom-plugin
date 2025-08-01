# Generated by Django 4.2.19 on 2025-07-30 10:08

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import model_utils.fields


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0004_auto_20230727_2054'),
        ('course_partnerships', '0004_partner_activate_school_admin'),
    ]

    operations = [
        migrations.CreateModel(
            name='PartnerOrganizationMapping',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', model_utils.fields.AutoCreatedField(default=django.utils.timezone.now, editable=False, verbose_name='created')),
                ('modified', model_utils.fields.AutoLastModifiedField(default=django.utils.timezone.now, editable=False, verbose_name='modified')),
                ('show_in_mobile_app', models.BooleanField(default=False, help_text='Controls whether this partner-organization mapping is shown in the mobile app.')),
                ('organization', models.ForeignKey(help_text='The organization linked to the partner.', on_delete=django.db.models.deletion.CASCADE, related_name='partner_mappings', to='organizations.organization')),
                ('partner', models.ForeignKey(help_text='The partner associated with the organization.', on_delete=django.db.models.deletion.CASCADE, related_name='organization_mappings', to='course_partnerships.partner')),
            ],
            options={
                'verbose_name': 'Partner-Organization Mapping',
                'verbose_name_plural': 'Partner-Organization Mappings',
                'unique_together': {('partner', 'organization')},
            },
        ),
    ]
