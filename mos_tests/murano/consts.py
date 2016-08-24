AddApplicationHost = '//a[contains(@class, "btn btn-default dropdown-toggle")]'
AddDockerStandaloneHost = '//a[contains(text(), "Docker Standalone Host")]'
WarningClose = '//div[@class="alert alert-warning alert-dismissable fade in"]//a'  # noqa

FilterSelector = '//input[@placeholder="Filter"]'
PackageNames = '//div[contains(@class, "table_header catalog")]/' \
               'following::div//h4'
PackageDetails = '//div[contains(@class, "table_header catalog")]/' \
                 'following::div//h4[text()="{}"]/..//' \
                 'a[contains(text(),"Details")]'
TextSearch = '//*[contains(text(), "{}")]'
SelectImage = '//select[@name="1-image"]'

# Buttons
ButtonNext = '//button[contains(text(), "Next")]'
ButtonCreate = '//button[contains(text(), "Create")]'
ButtonNextOnAddForm = '//form[@data-add-to-field="{}_0-host"]//div[@class="modal-footer"]//button[contains(text(), "Next")]'  # noqa
ButtonFilter = '//button[contains(text(), "Filter")]'
ButtonDeleteComp = '//button[contains(text(), "Delete Component")]'
ButtonConfDeleteComp = '//*[@id="modal_wrapper"]//' \
                       'a[contains(text(), "Delete Component")]'

ModalWindow = '//*[@id="modal_wrapper"]'
