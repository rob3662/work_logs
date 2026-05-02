/* === LICENSE HEADER START ===
Copyright (c) 2025 Robert Brake
This file is part of a proprietary software project.
Unauthorized use, modification, or distribution is strictly prohibited.
=== LICENSE HEADER END === */

// Theme management and utility functions for web apps

// Theme functionality
function toggleTheme() {
    const currentTheme = localStorage.getItem('theme') || 'light';
    const newTheme = currentTheme === 'light' ? 'dark' : 'light';
    localStorage.setItem('theme', newTheme);
    applyTheme(newTheme);
}

function applyTheme(theme) {
    if (theme === 'auto') {
        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        document.documentElement.setAttribute('data-theme', prefersDark ? 'dark' : 'light');
    } else {
        document.documentElement.setAttribute('data-theme', theme);
    }
    
    // Update theme icon
    const themeIcon = document.getElementById('theme-icon');
    if (themeIcon) {
        themeIcon.className = theme === 'dark' ? 'fas fa-sun' : 'fas fa-moon';
    }
}

// Initialize theme on page load
document.addEventListener('DOMContentLoaded', function() {
    const savedTheme = localStorage.getItem('theme') || 'light';
    applyTheme(savedTheme);
    
    // Listen for system theme changes
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function(e) {
        if (localStorage.getItem('theme') === 'auto') {
            applyTheme('auto');
        }
    });
});

// Utility functions
function showAlert(message, type = 'info') {
    const alertContainer = document.createElement('div');
    alertContainer.className = `alert alert-${type} alert-dismissible fade show`;
    alertContainer.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    
    // Insert at the top of the main content
    const main = document.querySelector('main');
    if (main) {
        main.insertBefore(alertContainer, main.firstChild);
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
