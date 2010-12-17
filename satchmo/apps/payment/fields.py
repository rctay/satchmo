from django.db import models
from payment.config import credit_choices, labelled_gateway_choices

class CreditChoiceCharField(models.CharField):

    def __init__(self, *args, **kwargs):
        choices = kwargs.pop("choices", "__DYNAMIC__")
        if choices == "__DYNAMIC__":
            kwargs['choices'] = credit_choices()

        super(CreditChoiceCharField, self).__init__(*args, **kwargs)

class PaymentChoiceCharField(models.CharField):
    
    def __init__(self, *args, **kwargs):
        choices = kwargs.pop("choices", "__DYNAMIC__")
        if choices == "__DYNAMIC__":
            kwargs['choices'] = labelled_gateway_choices()
                    
        super(PaymentChoiceCharField, self).__init__(*args, **kwargs)

try:
    # South introspection rules for our custom field.
    from south.modelsinspector import add_introspection_rules, matching_details

    # get the kwargs for a Field instance
    # we're using Field, as CharField doesn't change __init__()
    _args, kwargs = matching_details(models.Field())

    add_introspection_rules([(
        (CreditChoiceCharField, ),
        [],
        kwargs,
    )], ['payment\.fields\.CreditChoiceCharField'])
    add_introspection_rules([(
        (PaymentChoiceCharField, ),
        [],
        kwargs,
    )], ['payment\.fields\.PaymentChoiceCharField'])
except ImportError:
    pass
