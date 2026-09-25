(function ($) {
  "use strict";

  // Spinner
  var spinner = function () {
    setTimeout(function () {
      if ($("#spinner").length > 0) {
        $("#spinner").removeClass("show");
      }
    }, 1);
  };
  spinner();

  // Initiate the wowjs
  new WOW().init();

  // Sticky Navbar
  $(window).scroll(function () {
    if ($(this).scrollTop() > 40) {
      $(".sticky-top").addClass("shadow-sm is-scrolled").css("top", "0px");
    } else {
      $(".sticky-top").removeClass("shadow-sm is-scrolled").css("top", "0px");
    }
  });

  // Back to top button
  $(window).scroll(function () {
    if ($(this).scrollTop() > 300) {
      $(".back-to-top").fadeIn("slow");
    } else {
      $(".back-to-top").fadeOut("slow");
    }
  });
  $(".back-to-top").click(function () {
    $("html, body").animate({ scrollTop: 0 }, 1500, "easeInOutExpo");
    return false;
  });

  // Facts counter
  $('[data-toggle="counter-up"]').counterUp({
    delay: 10,
    time: 2000,
  });

  // Testimonials carousel
  $(".testimonial-carousel").owlCarousel({
    autoplay: true,
    smartSpeed: 1000,
    items: 1,
    dots: false,
    loop: true,
    nav: true,
    navText: [
      '<i class="bi bi-chevron-left"></i>',
      '<i class="bi bi-chevron-right"></i>',
    ],
  });
})(jQuery);

document.addEventListener("DOMContentLoaded", function () {
  // Get the current page path
  const currentPath = window.location.pathname.split("/").pop();

  // Get all nav links
  const navLinks = document.querySelectorAll(".navbar-nav .nav-link");

  // Loop through nav links and set the active class if href matches current path
  navLinks.forEach((link) => {
    if (link.getAttribute("href") === currentPath) {
      link.classList.add("active");
    }
  });
});
