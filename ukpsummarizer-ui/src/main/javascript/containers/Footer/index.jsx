/**
 * Hendrik Lücke-Tieke
 * dataexpedition.net
 *
 * Copyright (c) 2017 Hendrik Lücke-Tieke. All rights reserved.
 *
 * Do not use without prior consent by the copyright holder.
 *
 **/

import React from 'react';

import {
    LinkContainer,
    IndexLinkContainer
} from 'react-router-bootstrap';

import {
    Navbar,
    Nav,
    NavItem,
    MenuItem
} from 'react-bootstrap';

import {connect} from 'react-redux';
import {bindActionCreators} from 'redux';
import FontAwesome from 'react-fontawesome';

import './footer.less';
import routeConfig from '../../config/routes';
import * as UserActions from '../../controllers/user/actions';

const Footer = (props) => {
    const {store, actions} = props;

    let username = store.users.user.id;
    return (
        <Navbar fixedBottom>
             <Navbar.Text>
                   &copy; 2018 UKP Lab, Technische Universität Darmstadt
             </Navbar.Text>

            <Nav className="center">
                <IndexLinkContainer to={routeConfig.profile} disabled>
                    <NavItem eventKey={5}><FontAwesome name="user" fixedWidth/>&nbsp; User ID: &nbsp;{username}</NavItem>
                </IndexLinkContainer>
            </Nav>

            <Nav pullRight>
                <LinkContainer to={routeConfig.root}>
                                 <NavItem eventKey={1}>Home</NavItem>
                             </LinkContainer>
            </Nav>

        </Navbar>);
};


/**
 * Maps values from the application state to properties
 * of the container component.
 * @param state {State} - the current application state
 */
const mapStateToProps = ({users, app} = state) => ({
    store: {
        users,
        app
    }
});

/**
 * Maps action dispatchers to properties of the container
 * component.
 *
 * @param dispatch {Dispatch} - the stores dispatch function.
 */
const mapDispatchToProps = (dispatch) => ({
    actions: bindActionCreators(Object.assign({}, UserActions), dispatch)
});

export default connect(mapStateToProps, mapDispatchToProps)(Footer);
