/* === LICENSE HEADER START ===
Copyright (c) 2026 Robert Brake
This file is part of a proprietary software project.
Unauthorized use, modification, or distribution is strictly prohibited.
=== LICENSE HEADER END === */

(function () {
  "use strict";

  function initWorkLogDatePickers() {
    if (typeof flatpickr === "undefined") {
      return;
    }
    var nodes = document.querySelectorAll("input.work-log-datepicker");
    nodes.forEach(function (el) {
      if (el._flatpickr) {
        return;
      }
      flatpickr(el, {
        dateFormat: "Y-m-d",
        allowInput: false,
        disableMobile: true,
        locale: { firstDayOfWeek: 0 },
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initWorkLogDatePickers);
  } else {
    initWorkLogDatePickers();
  }
})();
