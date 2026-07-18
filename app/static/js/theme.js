/* === LICENSE HEADER START ===
Copyright (c) 2025 Robert Brake
This file is part of a proprietary software project.
Unauthorized use, modification, or distribution is strictly prohibited.
=== LICENSE HEADER END === */

// Theme management and utility functions for web apps

// Theme functionality
function resolveTheme(theme) {
    if (theme === 'auto') {
        return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }
    return theme === 'dark' ? 'dark' : 'light';
}

function toggleTheme() {
    const currentTheme = localStorage.getItem('theme') || 'light';
    const newTheme = resolveTheme(currentTheme) === 'light' ? 'dark' : 'light';
    localStorage.setItem('theme', newTheme);
    applyTheme(newTheme);
}

function applyTheme(theme) {
    const effective = resolveTheme(theme);
    const root = document.documentElement;
    // data-theme: custom CSS; data-bs-theme: Bootstrap 5.3 color modes
    root.setAttribute('data-theme', effective);
    root.setAttribute('data-bs-theme', effective);

    const themeIcon = document.getElementById('theme-icon');
    if (themeIcon) {
        themeIcon.className = effective === 'dark' ? 'fas fa-sun' : 'fas fa-moon';
    }
}

// Apply as soon as this script runs (end of body) so paint matches preference
applyTheme(localStorage.getItem('theme') || 'light');

document.addEventListener('DOMContentLoaded', function() {
    applyTheme(localStorage.getItem('theme') || 'light');

    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function() {
        if (localStorage.getItem('theme') === 'auto') {
            applyTheme('auto');
        }
    });

    // Flash / dismissible alerts: auto-close after a few seconds unless the user dismisses sooner
    document.querySelectorAll('main .alert.alert-dismissible').forEach(function (el) {
        scheduleAlertAutoDismiss(el);
    });
});

const ALERT_AUTO_DISMISS_MS = 5000;

function scheduleAlertAutoDismiss(alertEl, delayMs) {
    if (!alertEl || alertEl.dataset.autoDismissScheduled === '1') {
        return;
    }
    // Keep error/danger alerts until the user closes them
    if (alertEl.classList.contains('alert-danger')) {
        return;
    }
    alertEl.dataset.autoDismissScheduled = '1';
    const ms = typeof delayMs === 'number' ? delayMs : ALERT_AUTO_DISMISS_MS;
    window.setTimeout(function () {
        if (!alertEl.isConnected) {
            return;
        }
        if (typeof bootstrap !== 'undefined' && bootstrap.Alert) {
            bootstrap.Alert.getOrCreateInstance(alertEl).close();
        } else {
            alertEl.remove();
        }
    }, ms);
}

// Utility functions
function showAlert(message, type = 'info') {
    const alertContainer = document.createElement('div');
    alertContainer.className = `alert alert-${type} alert-dismissible fade show`;
    alertContainer.setAttribute('role', 'alert');
    alertContainer.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
    `;

    const main = document.querySelector('main');
    if (main) {
        main.insertBefore(alertContainer, main.firstChild);
        scheduleAlertAutoDismiss(alertContainer);
    }
}

function showLoading(element) {
    if (element) {
        element.classList.add('loading');
        element.disabled = true;
    }
}

function hideLoading(element) {
    if (element) {
        element.classList.remove('loading');
        element.disabled = false;
    }
}

// Form validation helpers
function validateEmail(email) {
    const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return re.test(email);
}

function validatePassword(password) {
    // At least 8 characters, 1 uppercase, 1 lowercase, 1 number, 1 symbol
    const re = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*(),.?":{}|<>]).{8,}$/;
    return re.test(password);
}

// API helpers
async function apiCall(url, options = {}) {
    const defaultOptions = {
        headers: {
            'Content-Type': 'application/json',
            'X-CSRF-Token': document.querySelector('meta[name="csrf-token"]')?.content || ''
        }
    };
    
    const mergedOptions = { ...defaultOptions, ...options };
    
    try {
        const response = await fetch(url, mergedOptions);
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.error || 'An error occurred');
        }
        
        return data;
    } catch (error) {
        console.error('API call failed:', error);
        showAlert(error.message, 'danger');
        throw error;
    }
}

// Work day management
function confirmDelete(message = 'Are you sure you want to delete this item?') {
    return confirm(message);
}

function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-CA'); // YYYY-MM-DD format
}

function formatCurrency(amount) {
    return new Intl.NumberFormat('en-CA', {
        style: 'currency',
        currency: 'CAD'
    }).format(amount);
}

// Export functions for global use
window.toggleTheme = toggleTheme;
window.applyTheme = applyTheme;
window.showAlert = showAlert;
window.showLoading = showLoading;
window.hideLoading = hideLoading;
window.validateEmail = validateEmail;
window.validatePassword = validatePassword;
window.apiCall = apiCall;
window.confirmDelete = confirmDelete;
window.formatDate = formatDate;
window.formatCurrency = formatCurrency;
