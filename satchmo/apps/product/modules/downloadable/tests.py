from django.conf import settings
from django.contrib.sites.models import Site
from django.core import urlresolvers
from django.core.files import File
from django.http import HttpResponse
from django.test import TestCase
from django.test.client import Client
from l10n.models import Country
from livesettings import config_value
from product.models import Product
from product.modules.downloadable.models import DownloadLink, DownloadableProduct
from satchmo_store.contact.models import AddressBook, Contact
from satchmo_store.shop.models import Cart, Order
from shipping.modules.flat.shipper import Shipper as flat
from shipping.modules.per.shipper import Shipper as per

import datetime
from decimal import Decimal
import keyedcache
import os
from shutil import rmtree
from tempfile import mkdtemp, mkstemp

class DownloadableShippingTest(TestCase):

    fixtures = ['l10n-data.yaml','test_shop.yaml']

    def setUp(self):
        self.site = Site.objects.get_current()
        self.product1 = Product.objects.create(slug='p1', name='p1', site=self.site)
        self.cart1 = Cart.objects.create(site=self.site)
        self.cartitem1 = self.cart1.add_item(self.product1, 3)

    def tearDown(self):
        keyedcache.cache_delete()

    def test_downloadable_zero_shipping(self):
        subtype2 = DownloadableProduct.objects.create(product=self.product1)
        self.assertEqual(self.product1.get_subtypes(), ('DownloadableProduct',))

        self.assertFalse(subtype2.is_shippable)
        self.assertFalse(self.product1.is_shippable)
        self.assertFalse(self.cart1.is_shippable)
        self.assertEqual(flat(self.cart1, None).cost(), Decimal("0.00"))
        self.assertEqual(per(self.cart1, None).cost(), Decimal("0.00"))

class DownloadableProductTest(TestCase):
    fixtures = ['l10n-data.yaml', 'products.yaml']

    def setUp(self):
        self.site = Site.objects.get_current()

        # setup the protected dir
        self.protected_dir = os.path.normcase(os.path.normpath(os.path.join(
            settings.MEDIA_ROOT,
            config_value('PRODUCT', 'PROTECTED_DIR')
        )))
        if not os.path.isdir(self.protected_dir):
            os.makedirs(self.protected_dir)

        # setup a temporary file in the protected dir
        # this is the file that django will use during this test, but we won't
        # use it; close and remove it.
        _file, _abs_path = mkstemp(dir=self.protected_dir)
        os.close(_file)
        os.remove(_abs_path)
        self.file_name = _abs_path.split(os.path.sep)[-1]

        # setup a temporary source dir and source file, using the same file name
        # generated eariler.
        self.dir = mkdtemp()
        self.file = open(os.path.join(self.dir, self.file_name), "w")

        # a fake SHA
        self.key = "".join(["12abf" for i in range(8)])

        # setup a contact
        c, _created = Contact.objects.get_or_create(
            first_name="Jim",
            last_name="Tester",
            email="Jim@JimWorld.com",
        )
        ad, _created = AddressBook.objects.get_or_create(
            contact=c, description="home",
            street1 = "test", state="OR", city="Portland",
            country = Country.objects.get(iso2_code__iexact = 'US'),
            is_default_shipping=True,
            is_default_billing=True,
        )

        # setup a order
        o, _created = Order.objects.get_or_create(contact=c, shipping_cost=Decimal('6.00'), site=self.site)

        # setup download
        self.product, _created = DownloadableProduct.objects.get_or_create(
            product=Product.objects.get(slug='dj-rocks'),
            file=File(self.file),
            num_allowed_downloads=3,
            expire_minutes=1,
        )
        self.product_link, _created = DownloadLink.objects.get_or_create(
            downloadable_product=self.product,
            order=o, key=self.key, num_attempts=0,
            time_stamp=datetime.datetime.now()
        )

        # setup client
        self.domain = 'satchmoserver'
        self.client = Client(SERVER_NAME=self.domain)

    def tearDown(self):
        self.file.close()
        rmtree(self.dir)
        os.remove(os.path.join(self.protected_dir, self.file_name))

    def test_download_link(self):
        """Test that we are able to download a product."""

        pd_url = urlresolvers.reverse('satchmo_download_send', kwargs= {'download_key': self.key})

        # first, hit the url.
        response = self.client.get(pd_url)
        self.assertEqual(response['Location'],
            'http://%s%s' % (
                self.domain,
                urlresolvers.reverse('satchmo_download_process', kwargs= {'download_key': self.key}),
            )
        )

        # follow the redirect to "process" the key.
        response = self.client.get(response['Location'])
        self.assertEqual(self.client.session.get('download_key', None), self.key)

        # we should have gotten a page that says "click here".
        # hit the pd_url again; we should get a sendfile redirect.
        response = self.client.get(pd_url)

        # eg. /static/protected/file_name
        exp_url = "%s%s/%s" % (settings.MEDIA_URL, self.protected_dir.split(os.path.sep)[-1], self.file_name)

        self.assertEqual(response['X-Accel-Redirect'], exp_url)
        self.assertEqual(response['X-Sendfile'], exp_url)
        self.assertEqual(response['X-LIGHTTPD-send-file'], exp_url)
