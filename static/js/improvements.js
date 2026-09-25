// Improved JavaScript functionality for Amiri Insurance

document.addEventListener('DOMContentLoaded', function () {
    // Initialize improvements
    initFormValidation();
    initLazyLoading();
    initAccessibility();
    initPerformanceOptimizations();
});

// Form validation and handling
function initFormValidation() {
    const appointmentForm = document.querySelector('form[onsubmit*="sendMail"]');
    if (appointmentForm) {
        appointmentForm.addEventListener('submit', function (e) {
            e.preventDefault();
            handleAppointmentForm(this);
        });
    }

    const newsletterForm = document.getElementById('mc-embedded-subscribe-form');
    if (newsletterForm) {
        newsletterForm.addEventListener('submit', function (e) {
            e.preventDefault();
            handleNewsletterForm(this);
        });
    }
}

// Handle appointment form submission
function handleAppointmentForm(form) {
    const formData = new FormData(form);
    const submitBtn = form.querySelector('button[type="submit"]');

    // Show loading state
    submitBtn.classList.add('loading');
    submitBtn.disabled = true;

    // Validate form
    if (!validateForm(form)) {
        submitBtn.classList.remove('loading');
        submitBtn.disabled = false;
        return;
    }

    // Simulate form submission (replace with actual API call)
    setTimeout(() => {
        // Create email content
        const emailContent = createEmailContent(formData);

        // Open email client
        const mailtoLink = `mailto:info@amiriinsuranceagency.com?subject=Appointment Request&body=${encodeURIComponent(emailContent)}`;
        window.location.href = mailtoLink;

        // Show success message
        showMessage('Thank you! Your appointment request has been sent.', 'success');

        // Reset form
        form.reset();

        // Remove loading state
        submitBtn.classList.remove('loading');
        submitBtn.disabled = false;
    }, 1000);
}

// Handle newsletter form submission
function handleNewsletterForm(form) {
    const emailInput = form.querySelector('#emailInput');
    const submitBtn = form.querySelector('button[type="submit"]');
    const responseMessage = document.getElementById('responseMessage');

    if (!emailInput.value || !isValidEmail(emailInput.value)) {
        showMessage('Please enter a valid email address.', 'error');
        return;
    }

    // Show loading state
    submitBtn.classList.add('loading');
    submitBtn.disabled = true;

    // Simulate API call (replace with actual server-side implementation)
    setTimeout(() => {
        responseMessage.textContent = 'Thank you for subscribing! We\'ll keep you updated with the latest insurance news and tips.';
        responseMessage.className = 'success-message';
        emailInput.value = '';

        submitBtn.classList.remove('loading');
        submitBtn.disabled = false;
    }, 1000);
}

// Form validation
function validateForm(form) {
    const requiredFields = form.querySelectorAll('[required]');
    let isValid = true;

    requiredFields.forEach(field => {
        if (!field.value.trim()) {
            field.classList.add('is-invalid');
            isValid = false;
        } else {
            field.classList.remove('is-invalid');
        }
    });

    return isValid;
}

// Email validation
function isValidEmail(email) {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return emailRegex.test(email);
}

// Create email content from form data
function createEmailContent(formData) {
    const fields = {
        'gname': 'Name',
        'gmail': 'Email',
        'cname': 'Mobile',
        'prefDate': 'Preferred Date',
        'prefTime': 'Preferred Time',
        'insuranceType': 'Type of Insurance',
        'message': 'Message'
    };

    let content = 'Appointment Request Details:\n\n';

    for (let [key, label] of Object.entries(fields)) {
        const value = formData.get(key) || document.getElementById(key)?.value || '';
        if (value) {
            content += `${label}: ${value}\n`;
        }
    }

    return content;
}

// Show message to user
function showMessage(message, type = 'info') {
    const messageDiv = document.createElement('div');
    messageDiv.className = `alert alert-${type === 'success' ? 'success' : 'danger'} alert-dismissible fade show`;
    messageDiv.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;

    // Insert at the top of the page
    document.body.insertBefore(messageDiv, document.body.firstChild);

    // Auto-remove after 5 seconds
    setTimeout(() => {
        if (messageDiv.parentNode) {
            messageDiv.remove();
        }
    }, 5000);
}

// Lazy loading for images
function initLazyLoading() {
    if ('IntersectionObserver' in window) {
        const imageObserver = new IntersectionObserver((entries, observer) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    const img = entry.target;
                    img.src = img.dataset.src;
                    img.classList.remove('lazy');
                    imageObserver.unobserve(img);
                }
            });
        });

        document.querySelectorAll('img[data-src]').forEach(img => {
            imageObserver.observe(img);
        });
    }
}

// Accessibility improvements
function initAccessibility() {
    // Add ARIA labels to carousel controls
    const carouselControls = document.querySelectorAll('.carousel-control-prev, .carousel-control-next');
    carouselControls.forEach(control => {
        if (!control.getAttribute('aria-label')) {
            control.setAttribute('aria-label', control.classList.contains('carousel-control-prev') ? 'Previous slide' : 'Next slide');
        }
    });

    // Add focus management for modals
    const modals = document.querySelectorAll('.modal');
    modals.forEach(modal => {
        modal.addEventListener('shown.bs.modal', function () {
            const firstFocusable = modal.querySelector('input, button, select, textarea, [tabindex]:not([tabindex="-1"])');
            if (firstFocusable) {
                firstFocusable.focus();
            }
        });
    });
}

// Performance optimizations
function initPerformanceOptimizations() {
    // Debounce scroll events
    let scrollTimeout;
    window.addEventListener('scroll', function () {
        if (scrollTimeout) {
            clearTimeout(scrollTimeout);
        }
        scrollTimeout = setTimeout(() => {
            // Handle scroll-based functionality here
        }, 100);
    });

    // Preload critical resources
    const criticalImages = [
        '/static/img/icon/icon-02-primary.png',
        '/static/img/icon/icon-02-light.png'
    ];

    criticalImages.forEach(src => {
        const link = document.createElement('link');
        link.rel = 'preload';
        link.as = 'image';
        link.href = src;
        document.head.appendChild(link);
    });
}

// Enhanced sendMail function (backward compatibility)
function sendMail() {
    const form = document.querySelector('form[onsubmit*="sendMail"]');
    if (form) {
        handleAppointmentForm(form);
    }
}

// Add smooth scrolling for anchor links
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
        e.preventDefault();
        const target = document.querySelector(this.getAttribute('href'));
        if (target) {
            target.scrollIntoView({
                behavior: 'smooth',
                block: 'start'
            });
        }
    });
});

// Add keyboard navigation for carousel
document.addEventListener('keydown', function (e) {
    const activeCarousel = document.querySelector('.carousel.active');
    if (activeCarousel) {
        if (e.key === 'ArrowLeft') {
            const prevBtn = activeCarousel.querySelector('.carousel-control-prev');
            if (prevBtn) prevBtn.click();
        } else if (e.key === 'ArrowRight') {
            const nextBtn = activeCarousel.querySelector('.carousel-control-next');
            if (nextBtn) nextBtn.click();
        }
    }
}); 