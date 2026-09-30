$(function () {
  var DEFAULT_SELECTED_METHOD = window.CHECKOUT_DEFAULT_SELECTED_METHOD;

  // Each `code` is a gateway wire value sent back as `selectedPaymentMethod` / `allowedPaymentMethods`.
  var PAYMENT_METHODS = [
    {code: 'PmPgCard', name: 'Credit / debit card', category: 'Cards'},
    {code: 'TouchNGoEWallet', name: "Touch 'n Go eWallet", category: 'E-wallets'},
    {code: 'GrabPay', name: 'GrabPay', category: 'E-wallets'},
    {code: 'Maybank', name: 'Maybank FPX', category: 'Online banking'},
    {code: 'Cimb', name: 'CIMB Clicks', category: 'Online banking'},
    {code: 'PublicBank', name: 'Public Bank', category: 'Online banking'}
  ];

  var PILL_CLASSES = 'pill rounded-full border border-slate-300 bg-white px-3.5 py-1.5 text-xs font-semibold '
      + 'text-slate-500 transition-colors hover:border-slate-400 hover:text-slate-900 '
      + 'data-[active=true]:border-indigo-600 data-[active=true]:bg-indigo-600 data-[active=true]:text-white';
  var METHOD_ROW_CLASSES = 'method-row flex cursor-pointer items-center gap-3 rounded-lg border '
      + 'border-slate-300 bg-white p-3 transition-colors hover:border-slate-400 '
      + 'has-[input:checked]:border-indigo-600 has-[input:checked]:bg-indigo-50 '
      + 'has-[input:checked]:ring-1 has-[input:checked]:ring-indigo-600';

  var HIDDEN_DESC = 'Off: shopper selects after redirect, on the Presto payment page';
  var SHOWN_DESC = 'On: shopper selects here, before paying';
  var HIDDEN_HINT = 'Enter the amount and description. You will choose how to pay on the next page.';
  var SHOWN_HINT = 'Enter the amount and description, then choose how you want to pay.';
  var HIDDEN_FOOTNOTE = 'Secure and encrypted';
  var SHOWN_FOOTNOTE = 'Secure and encrypted. Card details are entered on the Presto secure page next.';
  var HIDDEN_LABEL = 'Continue to Payment';
  var ERROR_FIELD_IDS = ['amountInRinggit', 'displayDesc', 'selectedPaymentMethod'];

  var $checkoutForm = $('#checkoutForm');
  var $submitButton = $('#submitButton');
  var $checkoutAlert = $('#checkoutAlert');
  var $checkoutAlertMessage = $('#checkoutAlertMessage');
  var $toggle = $('#showPaymentMethods');
  var $toggleDesc = $('#toggleDesc');
  var $methodSection = $('#methodSection');
  var $checkoutHint = $('#checkoutHint');
  var $submitButtonLabel = $('#submitButtonLabel');
  var $checkoutFootnote = $('#checkoutFootnote');
  var $amountInput = $('#amountInRinggit');
  var $categoryPills = $('#categoryPills');
  var $methodList = $('#methodList');

  function iconClassFor(category) {
    if (category === 'Cards') {
      return 'fa-credit-card';
    }
    if (category === 'Online banking') {
      return 'fa-building-columns';
    }
    return 'fa-wallet';
  }

  function renderPaymentMethods() {
    var categories = [];
    $.each(PAYMENT_METHODS, function (i, method) {
      if ($.inArray(method.category, categories) === -1) {
        categories.push(method.category);
      }
    });

    $categoryPills.empty().append(
        $('<button type="button" data-category="all" data-active="true">All</button>').addClass(PILL_CLASSES));
    $.each(categories, function (i, category) {
      $categoryPills.append($('<button type="button"></button>')
          .addClass(PILL_CLASSES)
          .attr('data-category', category)
          .text(category));
    });

    $methodList.empty();
    $.each(PAYMENT_METHODS, function (i, method) {
      var $radio = $('<input type="radio" name="selectedPaymentMethod"/>')
          .addClass('order-2 ml-auto h-[18px] w-[18px] shrink-0 accent-indigo-600')
          .val(method.code)
          .prop('checked', method.code === DEFAULT_SELECTED_METHOD);
      var $iconWrap = $('<span></span>')
          .addClass('flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-slate-200 '
              + 'bg-slate-100 text-slate-600')
          .append($('<i aria-hidden="true"></i>').addClass('fa-solid ' + iconClassFor(method.category)));
      var $name = $('<span></span>').addClass('min-w-0 flex-1 text-sm font-semibold').text(method.name);

      $('<label></label>')
          .addClass(METHOD_ROW_CLASSES)
          .attr('data-category', method.category)
          .append($radio, $iconWrap, $name)
          .appendTo($methodList);
    });
  }

  function currentAmountText() {
    var value = parseFloat($amountInput.val());
    return isNaN(value) ? '0.00' : value.toFixed(2);
  }

  function applyToggle() {
    var showMethods = $toggle.is(':checked');
    $methodSection.toggleClass('hidden', !showMethods);
    $toggleDesc.text(showMethods ? SHOWN_DESC : HIDDEN_DESC);
    $checkoutHint.text(showMethods ? SHOWN_HINT : HIDDEN_HINT);
    $checkoutFootnote.text(showMethods ? SHOWN_FOOTNOTE : HIDDEN_FOOTNOTE);
    $submitButtonLabel.text(showMethods ? ('Pay RM ' + currentAmountText()) : HIDDEN_LABEL);
  }

  function applyCategory(category) {
    $categoryPills.find('.pill').each(function () {
      $(this).attr('data-active', $(this).data('category') === category ? 'true' : 'false');
    });
    $methodList.find('.method-row').each(function () {
      var matches = category === 'all' || $(this).data('category') === category;
      $(this).toggleClass('hidden', !matches);
    });
  }

  function clearErrors() {
    $.each(ERROR_FIELD_IDS, function (i, field) {
      $('#' + field + 'Error').text('').addClass('hidden');
    });
    $checkoutAlertMessage.text('');
    $checkoutAlert.addClass('hidden');
  }

  function showFieldErrors(errors) {
    $.each(errors, function (field, message) {
      $('#' + field + 'Error').text(message).removeClass('hidden');
    });
  }

  function showAlert(messageText) {
    $checkoutAlertMessage.text(messageText);
    $checkoutAlert.removeClass('hidden');
  }

  function checkoutPayload() {
    var $checkedMethod = $methodList.find('input[name="selectedPaymentMethod"]:checked');
    return {
      displayDesc: $('#displayDesc').val(),
      amountInRinggit: $amountInput.val() === '' ? null : $amountInput.val(),
      showPaymentMethods: $toggle.is(':checked'),
      pageTitle: $('#pageTitle').val(),
      selectedPaymentMethod: $checkedMethod.length ? $checkedMethod.val() : null,
      receiptName: $('#receiptName').val(),
      receiptEmail: $('#receiptEmail').val()
    };
  }

  renderPaymentMethods();

  $toggle.on('change', applyToggle);
  $categoryPills.on('click', '.pill', function () {
    applyCategory($(this).data('category'));
  });
  $amountInput.on('input', function () {
    if ($toggle.is(':checked')) {
      $submitButtonLabel.text('Pay RM ' + currentAmountText());
    }
  });

  $checkoutForm.on('submit', function (event) {
    event.preventDefault();
    clearErrors();
    $submitButton.prop('disabled', true);

    $.ajax({
      url: '/checkout',
      method: 'POST',
      contentType: 'application/json',
      data: JSON.stringify(checkoutPayload()),
      dataType: 'json'
    }).done(function (body) {
      window.location.href = body.paymentUrl || ('/return/' + body.txnRefNum);
    }).fail(function (xhr) {
      var body = xhr.responseJSON || {};
      if (xhr.status === 400) {
        showFieldErrors(body);
      } else {
        showAlert(body.message || 'Could not start payment.');
      }
      $submitButton.prop('disabled', false);
    });
  });
});
